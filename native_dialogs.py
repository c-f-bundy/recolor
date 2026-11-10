#!/usr/bin/env python3
"""
Native file picker - Linux'ta zenity kullanarak sistem dosya penceresini acar.

v0.4.2: Acilis klasoru GARANTISI. Bazi zenity surumleri dizin yollarini
--filename bayragiyle kabul etmiyor; boyle surumlerde dosya penceresi
programin acildigi klasorden (recolor/) aciliyordu. Cozum: dialog acikken
prosesin calisma klasoru gecici olarak hedef klasore tasinir
(_gecici_klasor) -> hangi zenity surumu olursa olsun pencere dogru
klasorden acilir. Islem bitince eski konuma geri donulur.
"""

import os
import subprocess
import shutil
from contextlib import contextmanager
from pathlib import Path


def _zenity_available():
    return shutil.which('zenity') is not None


@contextmanager
def _gecici_klasor(hedef=None):
    """Dialog suresince calisma klasorunu gecici olarak degistirir (v0.4.2).

    zenity ayri bir proses olarak acilir ve CALISMA KLASORUNU devralir.
    Dolayisiyla --filename bayragini tanimayan surumlerde bile pencere
    dogru klasorden acilir. finally ile hata olsa bile eski konuma
    donulur; programin geri kalanini etkilemez."""
    eski = os.getcwd()
    try:
        if hedef and Path(hedef).exists():
            os.chdir(hedef)
        yield
    finally:
        try:
            os.chdir(eski)
        except Exception:
            pass


def _run_zenity(args):
    """zenity'yi boyut parametreleriyle calistirir.

    v0.4.1: pencere boyutu 900x600 (yukseklik = genisligin 2/3'u, kullanici
    istegi). Kullanilan zenity surumu bu bayraklari tanimiyorsa dialog
    'Unknown option' hatasyla HEMEN kapanir; bu durumda bayraksiz bir kez
    daha denenir -> dosya penceresi her surumde acilmaya devam eder."""
    sonuc = _zenity_calistir(['--width', '900', '--height', '600'] + args)
    if sonuc is not None:
        return sonuc
    return _zenity_calistir(args) or []


def _zenity_calistir(args):
    """Tek zenity denemesi. Boyut bayraklari taninmadiysa None doner
    (cagiran yeniden dener); iptal/hata icin [], basari icin yol listesi."""
    try:
        result = subprocess.run(
            ['zenity', '--file-selection'] + args,
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            if not output:
                return []
            return output.split('|')
        hata = (result.stderr or '')
        if 'Unknown option' in hata or 'unrecognized' in hata.lower():
            return None  # bayraklar taninmadi: boyutsuz tekrar dene
        return []
    except Exception:
        return []


def open_file(initial_dir=None, file_types=None, title="Dosya sec"):
    if _zenity_available():
        with _gecici_klasor(initial_dir):
            args = ['--title', title]
            if initial_dir and Path(initial_dir).exists():
                args += ['--filename', str(Path(initial_dir).resolve()) + '/']
            if file_types:
                for label, patterns in file_types:
                    pattern_list = patterns.split()
                    filter_str = f"{label} | " + " ".join(pattern_list)
                    args += ['--file-filter', filter_str]
                args += ['--file-filter', 'Tum dosyalar | *']
            files = _run_zenity(args)
            return files[0] if files else None
    else:
        from tkinter import filedialog
        return filedialog.askopenfilename(
            title=title, initialdir=initial_dir,
            filetypes=[(l, p) for l, p in file_types] if file_types else None
        )


def open_multiple_files(initial_dir=None, file_types=None, title="Dosya sec"):
    if _zenity_available():
        with _gecici_klasor(initial_dir):
            args = ['--title', title, '--multiple', '--separator', '|']
            if initial_dir and Path(initial_dir).exists():
                args += ['--filename', str(Path(initial_dir).resolve()) + '/']
            if file_types:
                for label, patterns in file_types:
                    filter_str = f"{label} | " + " ".join(patterns.split())
                    args += ['--file-filter', filter_str]
                args += ['--file-filter', 'Tum dosyalar | *']
            return _run_zenity(args)
    else:
        from tkinter import filedialog
        return list(filedialog.askopenfilenames(
            title=title, initialdir=initial_dir,
            filetypes=[(l, p) for l, p in file_types] if file_types else None
        ))


def open_directory(initial_dir=None, title="Klasor sec"):
    if _zenity_available():
        with _gecici_klasor(initial_dir):
            args = ['--title', title, '--directory']
            if initial_dir and Path(initial_dir).exists():
                args += ['--filename', str(Path(initial_dir).resolve()) + '/']
            files = _run_zenity(args)
            return files[0] if files else None
    else:
        from tkinter import filedialog
        return filedialog.askdirectory(title=title, initialdir=initial_dir)


def save_file(initial_dir=None, default_name=None, file_types=None, title="Kaydet"):
    if _zenity_available():
        with _gecici_klasor(initial_dir):
            args = ['--title', title, '--save', '--confirm-overwrite',
                    '--separator', '|']
            if initial_dir and Path(initial_dir).exists():
                full_path = str(Path(initial_dir).resolve() / (default_name or ''))
                args += ['--filename', full_path]
            if file_types:
                for label, patterns in file_types:
                    filter_str = f"{label} | " + " ".join(patterns.split())
                    args += ['--file-filter', filter_str]
                args += ['--file-filter', 'Tum dosyalar | *']
            files = _run_zenity(args)
            return files[0] if files else None
    else:
        from tkinter import filedialog
        return filedialog.asksaveasfilename(
            title=title, initialdir=initial_dir,
            initialfile=default_name,
            filetypes=[(l, p) for l, p in file_types] if file_types else None
        )


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    return path
