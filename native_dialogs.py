#!/usr/bin/env python3
"""
Native file picker - Linux'ta zenity kullanarak sistem dosya penceresini acar.

Bu modul Tkinter'in cirkin kendi dosya diyalogu yerine Linux desktop ortaminin
default dosya gezginini kullanir. zenity yuklu degilse tkinter'a geri doner.
"""

import subprocess
import shutil
import os
from pathlib import Path
from tkinter import filedialog, messagebox


def _zenity_available():
    """zenity kurulu mu kontrol et."""
    return shutil.which('zenity') is not None


def _run_zenity(args):
    """zenity'i calistir, secilen dosyalari dondur."""
    try:
        result = subprocess.run(
            ['zenity', '--file-selection'] + args,
            capture_output=True, text=True, check=False
        )
        if result.returncode == 0:
            # Cikti: dosya yollari '|' ile ayrilmis
            output = result.stdout.strip()
            if not output:
                return []
            return output.split('|')
        return []
    except Exception:
        return []


def open_file(initial_dir=None, file_types=None, title="Dosya sec"):
    """Tek dosya sec. Donus: str path veya None.

    file_types: ornek [("Jpeg", "*.jpg *.jpeg"), ("Png", "*.png")]
    """
    if _zenity_available():
        args = ['--title', title]
        if initial_dir and Path(initial_dir).exists():
            args += ['--filename', str(initial_dir) + '/']
        if file_types:
            # zenity --file-filter formatı
            for label, patterns in file_types:
                pattern_list = patterns.split()
                filter_str = f"{label} | " + " ".join(pattern_list)
                args += ['--file-filter', filter_str]
            # Tum dosyalar
            args += ['--file-filter', 'Tum dosyalar | *']
        files = _run_zenity(args)
        return files[0] if files else None
    else:
        # Fallback: tkinter
        return filedialog.askopenfilename(
            title=title, initialdir=initial_dir,
            filetypes=[(l, p) for l, p in file_types] if file_types else None
        )


def open_multiple_files(initial_dir=None, file_types=None, title="Dosya sec"):
    """Birden fazla dosya sec. Donus: list of str."""
    if _zenity_available():
        args = ['--title', title, '--multiple', '--separator', '|']
        if initial_dir and Path(initial_dir).exists():
            args += ['--filename', str(initial_dir) + '/']
        if file_types:
            for label, patterns in file_types:
                filter_str = f"{label} | " + " ".join(patterns.split())
                args += ['--file-filter', filter_str]
            args += ['--file-filter', 'Tum dosyalar | *']
        return _run_zenity(args)
    else:
        return list(filedialog.askopenfilenames(
            title=title, initialdir=initial_dir,
            filetypes=[(l, p) for l, p in file_types] if file_types else None
        ))


def open_directory(initial_dir=None, title="Klasor sec"):
    """Klasor sec. Donus: str path veya None."""
    if _zenity_available():
        args = ['--title', title, '--directory']
        if initial_dir and Path(initial_dir).exists():
            args += ['--filename', str(initial_dir) + '/']
        files = _run_zenity(args)
        return files[0] if files else None
    else:
        return filedialog.askdirectory(title=title, initialdir=initial_dir)


def save_file(initial_dir=None, default_name=None, file_types=None, title="Kaydet"):
    """Kayit dosyasi sec. Donus: str path veya None.

    Kullanici dosya adini degistirmeden kaydederse, initial_dir/default_name doner.
    """
    if _zenity_available():
        args = ['--title', title, '--save', '--confirm-overwrite', '--separator', '|']
        if initial_dir and Path(initial_dir).exists():
            full_path = str(Path(initial_dir) / (default_name or ''))
            args += ['--filename', full_path]
        if file_types:
            for label, patterns in file_types:
                filter_str = f"{label} | " + " ".join(patterns.split())
                args += ['--file-filter', filter_str]
            args += ['--file-filter', 'Tum dosyalar | *']
        files = _run_zenity(args)
        return files[0] if files else None
    else:
        return filedialog.asksaveasfilename(
            title=title, initialdir=initial_dir,
            initialfile=default_name,
            filetypes=[(l, p) for l, p in file_types] if file_types else None
        )


def ensure_dir(path):
    """Klasor yoksa olustur."""
    Path(path).mkdir(parents=True, exist_ok=True)
    return path
