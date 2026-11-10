#!/usr/bin/env python3
"""
Recolor GUI v0.4.0 - Renk Standardizasyon Araci

v0.4.0 degisiklikleri:
- Hayalet panel hatasi duzeltildi (GUI'nin bozuk yerlesim sebebi)
- Tek kaydirici modu (tension) TAMAMEN kaldirildi; 3 kaydirici:
  Yumusaklik, Yapisma (snap), Etki Gucu (strength) - her biri tek is
- Otomatik isleme kalkti: islem yalniz 'Onizle' basilinca baslar,
  onizleme acikken degisiklikler canli yansir (Secenek A)
- Damlaliga basinca onizleme kapanir, orijinal uzerinden renk secilir
- Ayni kaynak renk icin Vazgec/Degistir diyalogu
- Tek tik=sadece sec, cift tik=sec ve ac (cift tetiklenme duzeltildi)
- Grid sutun sayisi pencere genisligine uyarlanir; tekerlek=kaydirma,
  Ctrl+tekerlek=kucuk resim boyutu
- Sag ayar paneli sabit genislik; sol alan pencereye adapte olur
- Tam cozunurlukte kayit parca parca hesaplanir (RAM duzeltmesi)
- Cikista input/'daki yalniz oturum kopyalari temizlenir
- Ayni isimli dosyalar 'isim (1)' seklinde eklenir, eskisi ezilmez
- Gorsel yukleyip uzerine tiklayarak palet olusturma
- Arka plan islemleri artik Tk degiskenlerine dokunmaz (thread guvenligi)
"""

import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='skimage')

import tkinter as tk
from tkinter import ttk, messagebox
import json
import sys
import os
import shutil
import threading
import time
from pathlib import Path
from PIL import Image, ImageTk
import numpy as np

# Modul yollari
APP_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(APP_DIR))

from recolor_core import ColorWarp
from native_dialogs import (
    open_file, open_multiple_files, open_directory, save_file, ensure_dir
)


# ============================================================
# TEMA
# ============================================================

class Theme:
    BG = '#1e1e2e'
    BG_PANEL = '#2a2a3c'
    BG_INPUT = '#3a3a4e'
    BG_HOVER = '#4a4a5e'
    BG_LIST_ITEM = '#2e2e42'
    FG = '#e0e0e8'
    FG_MUTED = '#9090a0'
    ACCENT = '#89b4fa'
    ACCENT_DARK = '#5a7fb8'
    ACCENT_SELECTED = '#f9e2af'  # secili thumbnail cercevesi
    DANGER = '#f38ba8'
    SUCCESS = '#a6e3a1'
    BORDER = '#4a4a5e'
    SWATCH_BORDER = '#6a6a8e'
    THUMB_BG = '#15151f'


# ============================================================
# FONTLAR - DAHA BUYUK
# ============================================================

FONT_FAMILY = 'DejaVu Sans'
# v0.4.1: +2 punto (kullanicidan istek - okunabilirlik)
FONT_SMALL = (FONT_FAMILY, 14)
FONT_NORMAL = (FONT_FAMILY, 15)
FONT_LARGE = (FONT_FAMILY, 17)
FONT_TITLE = (FONT_FAMILY, 18, 'bold')
FONT_BUTTON = (FONT_FAMILY, 15)
FONT_BUTTON_LARGE = (FONT_FAMILY, 16, 'bold')


# ============================================================
# KLASOR YAPISI
# ============================================================

OUTPUT_DIR = APP_DIR / 'output'
PALETTES_DIR = APP_DIR / 'palettes'
INPUT_DIR = APP_DIR / 'input'

for d in (OUTPUT_DIR, PALETTES_DIR, INPUT_DIR):
    d.mkdir(parents=True, exist_ok=True)


# ============================================================
# ANA PENCERE
# ============================================================

class RecolorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Recolor v0.4.0 - Renk Standardizasyon Araci")
        # v0.4.1: sag panel 2 kat genisligine cikti (430->860); pencere de
        # ona gore genisletildi ki resim alani daralmasin
        # v0.4.2: panel 680'e daraltildi -> resim alani daha da genisledi
        self.root.geometry("1700x950")
        self.root.minsize(1100, 750)
        self.root.configure(bg=Theme.BG)

        # --- Durum ---
        self.image_list = []           # [Path, ...] yuklenen dosya yollari
        self.current_image_idx = -1    # grid view'de acik olan resim
        self.original_images = {}      # {Path: PIL Image}
        self.image_arrays = {}         # {Path: numpy array}
        self.thumbnails = {}           # {Path: ImageTk.PhotoImage}
        self.thumbnail_labels = {}     # {Path: tk.Label}
        self.selected_thumb = None     # Path veya None

        self.palette = []
        self.palette_swatches = []
        self.mappings = {}             # {Path: [{"src","dst"}, ...]}
        self.picked_source = None

        self.preview_array = None
        # {Path: numpy array} - TAM cozunurluk onizlemeler. 12MP resim ~36MB
        # yer kapladigi icin en fazla 4 resim tutulur; en eskisi atilir.
        self.preview_arrays = {}
        self.preview_mode = False
        self.preview_lock = threading.Lock()
        self.preview_job = None
        self._preview_gen = 0        # kaydirici oynarken eskimis isi atmak icin
        self._grid_job = None        # grid yerlesim debounce'u
        self._palette_job = None     # palet yeniden dizi debounce'u
        self._palette_cols = None    # su anki palet sutun sayisi
        self.session_files = []      # bu oturumda input/'a kopyalanan dosyalar

        self.zoom_factor = 1.0
        self.base_scale = 1.0
        self.thumb_size_var = 180  # grid view thumbnail boyutu (Ctrl+tekerlek ile degisir)

        # Toplu islem modu: 'per_image' (ayri ayri) veya 'all_same' (hepsine ayni)
        self.batch_mode = tk.StringVar(value='per_image')

        # Mapping'in hangi modda oldugunu takip:
        # 'per_image' = her resmin kendi mappings'i
        # 'all_same'  = self.shared_mappings kullanilir
        self.shared_mappings = []

        self._setup_theme()
        self._build_ui()
        self._setup_default_palette()

        # Klavye kisa yollari
        self.root.bind('<Left>', lambda e: self.prev_image())
        self.root.bind('<Right>', lambda e: self.next_image())

        # Pencere kapatma (X tusu): once oturum kopyalarini temizle
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    # ============================================================
    # TEMA
    # ============================================================

    def _setup_theme(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        style.configure('.', background=Theme.BG, foreground=Theme.FG,
                       font=FONT_NORMAL, borderwidth=0)
        style.configure('TFrame', background=Theme.BG)
        style.configure('TLabel', background=Theme.BG, foreground=Theme.FG,
                       font=FONT_NORMAL)
        style.configure('Muted.TLabel', background=Theme.BG,
                       foreground=Theme.FG_MUTED, font=FONT_SMALL)
        style.configure('Treeview', background=Theme.BG_PANEL,
                       foreground=Theme.FG, fieldbackground=Theme.BG_PANEL,
                       bordercolor=Theme.BORDER, font=FONT_NORMAL)
        style.configure('TScrollbar', background=Theme.BG_PANEL,
                       troughcolor=Theme.BG, bordercolor=Theme.BORDER)
        style.configure('TNotebook', background=Theme.BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=Theme.BG_PANEL,
                       foreground=Theme.FG_MUTED, padding=(20, 12),
                       font=FONT_NORMAL)
        style.map('TNotebook.Tab',
                 background=[('selected', Theme.ACCENT_DARK)],
                 foreground=[('selected', Theme.FG)])

    # ============================================================
    # UI INSAASI
    # ============================================================

    def _build_ui(self):
        # Ust menu
        menubar = tk.Menu(self.root, bg=Theme.BG_PANEL, fg=Theme.FG,
                         activebackground=Theme.BG_HOVER,
                         activeforeground=Theme.FG, borderwidth=0,
                         font=FONT_NORMAL)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0, bg=Theme.BG_PANEL, fg=Theme.FG,
                           activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                           font=FONT_NORMAL)
        file_menu.add_command(label="Dosya(lar) Yukle", command=self.load_files)
        file_menu.add_command(label="Klasor Yukle", command=self.load_directory)
        file_menu.add_command(label="Palet Yukle (.gpl)", command=self.load_palette_gpl)
        file_menu.add_command(label="Palet Kaydet (.gpl)", command=self.save_palette_gpl)
        file_menu.add_command(label="Eslesmeleri Kaydet (JSON)", command=self.save_mappings)
        file_menu.add_command(label="Eslesmeleri Yukle (JSON)", command=self.load_mappings)
        file_menu.add_separator()
        file_menu.add_command(label="Cikis", command=self.on_close)
        menubar.add_cascade(label="Dosya", menu=file_menu)

        # Ana yerlesim - sol weight=1 (büyür), sag weight=0 (sabit)
        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                                   bg=Theme.BG, sashwidth=4,
                                   sashrelief=tk.FLAT)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # ---------------- SOL: GORUNTU ALANI (tüm ekstra yeri alir) ----------------
        # v0.4.0: yanlislikla IKI KEZ eklenen panel duzeltildi (hayalet panel
        # GUI'nin yerlesimini bozuyordu). Tek sol panel var, pencereye adapte olur.
        image_frame = tk.Frame(main_paned, bg=Theme.BG)
        main_paned.add(image_frame, minsize=500, stretch='always')

        # Ust kontrol cubugu
        ctrl = tk.Frame(image_frame, bg=Theme.BG_PANEL, height=60)
        ctrl.pack(fill=tk.X)
        tk.Button(ctrl, text="Dosya Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=20, pady=12,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_files).pack(side=tk.LEFT, padx=4, pady=8)
        tk.Button(ctrl, text="Klasor Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=20, pady=12,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_directory).pack(side=tk.LEFT, padx=4, pady=8)
        self.preview_btn = tk.Button(ctrl, text="Onizle", bg=Theme.ACCENT, fg=Theme.BG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=20, pady=12,
                 activebackground=Theme.ACCENT_DARK, activeforeground=Theme.BG,
                 command=self.toggle_preview)
        self.preview_btn.pack(side=tk.LEFT, padx=4, pady=8)
        tk.Button(ctrl, text="Sonucu Kaydet", bg=Theme.SUCCESS, fg=Theme.BG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=20, pady=12,
                 activebackground='#88c885', activeforeground=Theme.BG,
                 command=self.save_result).pack(side=tk.LEFT, padx=4, pady=8)
        tk.Button(ctrl, text="HEPSINI ISLE", bg=Theme.DANGER, fg=Theme.BG,
                 font=FONT_BUTTON_LARGE, relief=tk.FLAT, padx=20, pady=10,
                 activebackground='#c46a82', activeforeground=Theme.BG,
                 command=self.process_all).pack(side=tk.RIGHT, padx=4, pady=8)

        # Zoom + navigasyon gostergesi
        nav = tk.Frame(image_frame, bg=Theme.BG_PANEL, height=40)
        nav.pack(fill=tk.X)

        tk.Button(nav, text="<", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON_LARGE, relief=tk.FLAT, padx=12, pady=6,
                 activebackground=Theme.BG_HOVER, command=self.prev_image).pack(
                     side=tk.LEFT, padx=4, pady=4)
        self.nav_info = tk.StringVar(value="0 / 0")
        tk.Label(nav, textvariable=self.nav_info, bg=Theme.BG_PANEL,
                fg=Theme.FG, font=FONT_NORMAL, padx=10).pack(side=tk.LEFT)
        tk.Button(nav, text=">", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON_LARGE, relief=tk.FLAT, padx=12, pady=6,
                 activebackground=Theme.BG_HOVER, command=self.next_image).pack(
                     side=tk.LEFT, padx=4, pady=4)

        tk.Button(nav, text="Grid View'a Don", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=12, pady=6,
                 activebackground=Theme.BG_HOVER, command=self.show_grid).pack(
                     side=tk.LEFT, padx=12)

        self.zoom_var = tk.StringVar(value="Zoom: 100%")
        tk.Label(nav, textvariable=self.zoom_var, bg=Theme.BG_PANEL,
                fg=Theme.FG_MUTED, font=FONT_SMALL).pack(side=tk.RIGHT, padx=15)

        # Goruntu canvasi (grid view ve tekil goruntu ayni canvas)
        canvas_frame = tk.Frame(image_frame, bg=Theme.THUMB_BG)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg=Theme.THUMB_BG,
                               highlightthickness=0, cursor='crosshair')
        h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL,
                                command=self.canvas.xview)
        v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL,
                                command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=h_scroll.set,
                            yscrollcommand=v_scroll.set)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        h_scroll.grid(row=1, column=0, sticky='ew')
        v_scroll.grid(row=0, column=1, sticky='ns')
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas.bind('<Button-1>', self.on_canvas_click)
        self.canvas.bind('<Motion>', self.on_canvas_motion)
        self.canvas.bind('<Leave>', lambda e: self.hover_label.config(
            text='--', bg=Theme.BG_PANEL, fg=Theme.FG_MUTED))
        self.canvas.bind('<MouseWheel>', self.on_mouse_wheel)
        self.canvas.bind('<Button-4>', self.on_wheel_button_4)
        self.canvas.bind('<Button-5>', self.on_wheel_button_5)
        self.canvas.bind('<Control-MouseWheel>', self.on_ctrl_wheel)
        self.canvas.bind('<Shift-MouseWheel>', self.on_shift_wheel)
        # Linux icin Ctrl+tekerlek (Button-4/5)
        self.canvas.bind('<Control-Button-4>', self._on_ctrl_button_4)
        self.canvas.bind('<Control-Button-5>', self._on_ctrl_button_5)
        self.canvas.bind('<Shift-Button-4>', lambda e: self._scroll_h(-1))
        self.canvas.bind('<Shift-Button-5>', lambda e: self._scroll_h(1))
        # Cift tikla grid view'a don (tekil goruntuden)
        self.canvas.bind('<Double-Button-1>', self.on_canvas_double_click)
        # Pencere boyutu degince grid sutun sayisini uyarla
        self.canvas.bind('<Configure>', self._on_canvas_resize)

        # Durum cubugu
        status = tk.Frame(image_frame, bg=Theme.BG_PANEL, height=32)
        status.pack(fill=tk.X)
        tk.Label(status, text="Hover:", bg=Theme.BG_PANEL, fg=Theme.FG_MUTED,
                font=FONT_SMALL).pack(side=tk.LEFT, padx=(10, 4))
        self.hover_label = tk.Label(status, text='--', bg=Theme.BG_PANEL,
                                   fg=Theme.FG_MUTED, width=18, anchor=tk.W,
                                   font=FONT_SMALL, padx=6)
        self.hover_label.pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="Hazir. Dosya veya klasor yukleyin.")
        tk.Label(status, textvariable=self.status_var, bg=Theme.BG_PANEL,
                fg=Theme.FG, font=FONT_SMALL).pack(side=tk.LEFT, padx=15)

        # ---------------- SAG: KONTROL (sabit genislik) ----------------
        # Sabit genislik: sadece ayirici cizgi suruklenirse BU OTURUMDA
        # degisir; pencere buyudukce yer SOL alana gider (stretch='never').
        # v0.4.2: panel 800->680, en kucuk genislik 750->600 (kullanici
        # istegi): soldaki resim alani daha da genisler.
        control_frame = tk.Frame(main_paned, bg=Theme.BG, width=680)
        main_paned.add(control_frame, minsize=600, width=680, stretch='never')

        notebook = ttk.Notebook(control_frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        work_tab = tk.Frame(notebook, bg=Theme.BG_PANEL)
        notebook.add(work_tab, text="  Calisma Alani  ")
        self._build_work_tab(work_tab)

        settings_tab = tk.Frame(notebook, bg=Theme.BG_PANEL)
        notebook.add(settings_tab, text="  Ayarlar  ")
        self._build_settings_tab(settings_tab)

    # ============================================================
    # CALISMA ALANI
    # ============================================================

    def _build_work_tab(self, parent):
        paned = tk.PanedWindow(parent, orient=tk.VERTICAL,
                              bg=Theme.BG_PANEL, sashwidth=4, sashrelief=tk.FLAT)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ----- UST: KAYNAK RENK + PALET (1.5x daha buyuk) -----
        top_frame = tk.Frame(paned, bg=Theme.BG_PANEL)
        paned.add(top_frame, minsize=400, height=650)

        # Kaynak renk
        src_frame = tk.LabelFrame(top_frame, text=" Kaynak Renk ",
                                 bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                 font=FONT_LARGE, bd=2,
                                 highlightbackground=Theme.BORDER,
                                 highlightthickness=1, padx=14, pady=14)
        src_frame.pack(fill=tk.X, padx=4, pady=4)

        src_top = tk.Frame(src_frame, bg=Theme.BG_PANEL)
        src_top.pack(fill=tk.X)

        self.source_swatch = tk.Label(src_top, bg='#808080', width=6, height=3,
                                     relief=tk.SOLID, bd=1,
                                     highlightbackground=Theme.SWATCH_BORDER,
                                     highlightthickness=1)
        self.source_swatch.pack(side=tk.LEFT, padx=(0, 10))

        self.source_rgb_var = tk.StringVar(
            value="Henuz secilmedi\n(gorsele tikla veya asagidan ayarla)")
        tk.Label(src_top, textvariable=self.source_rgb_var,
                bg=Theme.BG_PANEL, fg=Theme.FG, font=FONT_NORMAL,
                justify=tk.LEFT).pack(side=tk.LEFT)

        # RGB sliderlar
        rgb_frame = tk.Frame(src_frame, bg=Theme.BG_PANEL)
        rgb_frame.pack(fill=tk.X, pady=(10, 0))

        self.src_rgb_vars = [tk.IntVar(value=128), tk.IntVar(value=128),
                            tk.IntVar(value=128)]
        for i, ch in enumerate(['R', 'G', 'B']):
            row = tk.Frame(rgb_frame, bg=Theme.BG_PANEL)
            row.pack(fill=tk.X, pady=2)

            tk.Label(row, text=ch, bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                    font=FONT_LARGE, width=2).pack(side=tk.LEFT)

            scale = tk.Scale(row, from_=0, to=255, orient=tk.HORIZONTAL,
                            variable=self.src_rgb_vars[i], showvalue=False,
                            bg=Theme.BG_PANEL, fg=Theme.FG,
                            troughcolor=Theme.BG_INPUT, highlightthickness=0,
                            sliderrelief=tk.FLAT, activebackground=Theme.ACCENT_DARK,
                            length=180, resolution=1, font=FONT_SMALL,
                            command=lambda v, idx=i: self._on_src_rgb_change(idx))
            scale.pack(side=tk.LEFT, padx=6, fill=tk.X, expand=True)

            spin = tk.Spinbox(row, from_=0, to=255, increment=1, width=5,
                            textvariable=self.src_rgb_vars[i], font=FONT_NORMAL,
                            bg=Theme.BG_INPUT, fg=Theme.FG, relief=tk.FLAT,
                            buttonbackground=Theme.BG_HOVER,
                            buttonuprelief=tk.FLAT, buttondownrelief=tk.FLAT,
                            highlightthickness=0, bd=0,
                            command=lambda idx=i: self._on_src_rgb_spin(idx))
            spin.pack(side=tk.LEFT, padx=(6, 0))

        tk.Button(src_frame, text="Bu rengi kaynak olarak kullan",
                 bg=Theme.ACCENT, fg=Theme.BG, font=FONT_BUTTON,
                 relief=tk.FLAT, padx=12, pady=8,
                 activebackground=Theme.ACCENT_DARK, activeforeground=Theme.BG,
                 command=self._use_rgb_as_source).pack(pady=(10, 0), fill=tk.X)

        # Palet (kaynagin altinda)
        pal_frame = tk.LabelFrame(top_frame, text=" Palet (hedef icin tikla) ",
                                 bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                 font=FONT_LARGE, bd=2,
                                 highlightbackground=Theme.BORDER,
                                 highlightthickness=1, padx=14, pady=14)
        pal_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        pal_ctrl = tk.Frame(pal_frame, bg=Theme.BG_PANEL)
        pal_ctrl.pack(fill=tk.X, pady=(0, 8))
        tk.Button(pal_ctrl, text=".gpl Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=8,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_palette_gpl).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text=".gpl Kaydet", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=8,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.save_palette_gpl).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text="RGB Ekle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=8,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.add_color_manual).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text="Gorselden Ekle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=8,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.open_palette_from_image).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text="Temizle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=8,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.clear_palette).pack(side=tk.LEFT, padx=2)
        self.palette_info_var = tk.StringVar(value="0 renk")
        tk.Label(pal_ctrl, textvariable=self.palette_info_var, bg=Theme.BG_PANEL,
                fg=Theme.FG_MUTED, font=FONT_SMALL).pack(side=tk.RIGHT, padx=4)

        pal_canvas_frame = tk.Frame(pal_frame, bg=Theme.BG_PANEL)
        pal_canvas_frame.pack(fill=tk.BOTH, expand=True)
        self.palette_canvas = tk.Canvas(pal_canvas_frame, bg=Theme.BG_PANEL,
                                       highlightthickness=0)
        pal_scroll = ttk.Scrollbar(pal_canvas_frame, orient=tk.VERTICAL,
                                   command=self.palette_canvas.yview)
        self.palette_inner = tk.Frame(self.palette_canvas, bg=Theme.BG_PANEL)
        self.palette_inner.bind("<Configure>",
            lambda e: self.palette_canvas.configure(
                scrollregion=self.palette_canvas.bbox("all")))
        self.palette_window_id = self.palette_canvas.create_window(
            (0, 0), window=self.palette_inner, anchor="nw")
        self.palette_canvas.bind("<Configure>", self._on_palette_resize)
        self.palette_canvas.configure(yscrollcommand=pal_scroll.set)
        self.palette_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pal_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # ----- ALT: ESLESMELER (sonsuz uzayacak) -----
        bot_frame = tk.Frame(paned, bg=Theme.BG_PANEL)
        paned.add(bot_frame, minsize=200)

        list_frame = tk.LabelFrame(bot_frame, text=" Eslesmeler ",
                                  bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                  font=FONT_LARGE, bd=2,
                                  highlightbackground=Theme.BORDER,
                                  highlightthickness=1, padx=14, pady=14)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        list_canvas_frame = tk.Frame(list_frame, bg=Theme.BG_PANEL)
        list_canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.list_canvas = tk.Canvas(list_canvas_frame, bg=Theme.BG_PANEL,
                                    highlightthickness=0)
        list_scroll = ttk.Scrollbar(list_canvas_frame, orient=tk.VERTICAL,
                                    command=self.list_canvas.yview)
        self.list_inner = tk.Frame(self.list_canvas, bg=Theme.BG_PANEL)
        self.list_inner.bind("<Configure>",
            lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all")))
        self.list_window_id = self.list_canvas.create_window(
            (0, 0), window=self.list_inner, anchor="nw")
        self.list_canvas.bind("<Configure>",
            lambda e: self.list_canvas.itemconfig(self.list_window_id, width=e.width))
        self.list_canvas.configure(yscrollcommand=list_scroll.set)
        self.list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        list_btn = tk.Frame(list_frame, bg=Theme.BG_PANEL)
        list_btn.pack(fill=tk.X, pady=(6, 0))
        tk.Button(list_btn, text="Tumunu Sil", bg=Theme.DANGER, fg=Theme.BG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=8,
                 activebackground='#c46a82', activeforeground=Theme.BG,
                 command=self.clear_mappings).pack(side=tk.LEFT, padx=2)
        tk.Button(list_btn, text="Kaydet", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=8,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.save_mappings).pack(side=tk.RIGHT, padx=2)
        tk.Button(list_btn, text="Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=8,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_mappings).pack(side=tk.RIGHT, padx=2)

    # ============================================================
    # AYARLAR
    # ============================================================

    def _build_settings_tab(self, parent):
        container = tk.Frame(parent, bg=Theme.BG_PANEL, padx=20, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        # Toplu islem modu
        batch_frame = tk.LabelFrame(container, text=" Toplu Islem Modu ",
                                   bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                   font=FONT_LARGE, bd=2,
                                   highlightbackground=Theme.BORDER,
                                   highlightthickness=1, padx=18, pady=16)
        batch_frame.pack(fill=tk.X, pady=8)

        tk.Radiobutton(batch_frame, text="  Her resim icin ayri eslestirme (default)",
                      variable=self.batch_mode, value='per_image',
                      bg=Theme.BG_PANEL, fg=Theme.FG, selectcolor=Theme.BG_INPUT,
                      activebackground=Theme.BG_PANEL, activeforeground=Theme.FG,
                      font=FONT_NORMAL, highlightthickness=0, bd=0,
                      command=self.on_batch_mode_change).pack(anchor=tk.W, pady=6)
        tk.Radiobutton(batch_frame, text="  Tum resimlere ayni eslestirme uygula",
                      variable=self.batch_mode, value='all_same',
                      bg=Theme.BG_PANEL, fg=Theme.FG, selectcolor=Theme.BG_INPUT,
                      activebackground=Theme.BG_PANEL, activeforeground=Theme.FG,
                      font=FONT_NORMAL, highlightthickness=0, bd=0,
                      command=self.on_batch_mode_change).pack(anchor=tk.W, pady=6)
        tk.Label(batch_frame,
                text="Ayri: her resim kendi eslesmelerini kullanir.\n"
                     "Ayni: tek bir eslestirme listesi tum resimlere uygulanir.",
                bg=Theme.BG_PANEL, fg=Theme.FG_MUTED, font=FONT_SMALL,
                justify=tk.LEFT).pack(anchor=tk.W, pady=(6, 0))

        # Donusum kaydiricilari (v0.4.0: mod secimi kalkti, 3 kaydirici)
        sliders_frame = tk.LabelFrame(container, text=" Donusum Ayarlari ",
                                      bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                      font=FONT_LARGE, bd=2,
                                      highlightbackground=Theme.BORDER,
                                      highlightthickness=1, padx=18, pady=16)
        sliders_frame.pack(fill=tk.X, pady=8)
        self._add_slider(sliders_frame, "Yumusaklik (etki genisligi)",
                        'softness', 0.0, 1.0, 0.5,
                        "Kalan renkler hedefe nasil ulasir?\n"
                        "0 = net ve dar gecisler, 1 = yumusak ve genis gecisler")
        self._add_slider(sliders_frame, "Yapisma (palet oturmasi)",
                        'snap', 0.0, 1.0, 0.0,
                        "Eslesen renkler hedefe ne kadar tam otursun?\n"
                        "0 = dogal gecis, 1 = renkler tam palet rengine yapisir")
        self._add_slider(sliders_frame, "Etki Gucu (opaklik)",
                        'strength', 0.0, 1.0, 1.0,
                        "Sonucun orijinalle karisimi:\n"
                        "0 = orijinal goruntu, 1 = tamamen donusmus goruntu")

        info_frame = tk.LabelFrame(container, text=" Bilgi ",
                                  bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                  font=FONT_LARGE, bd=2,
                                  highlightbackground=Theme.BORDER,
                                  highlightthickness=1, padx=18, pady=16)
        info_frame.pack(fill=tk.BOTH, expand=True, pady=8)
        tk.Label(info_frame,
                text="Klasor yapisi:\n"
                     f"  {APP_DIR}\n"
                     f"    input/     -> yuklenen dosyalarin kopyasi\n"
                     f"    output/    -> islenmis sonuclar\n"
                     f"    palettes/  -> palet dosyalari\n\n"
                     "Kisayollar (tekil goruntu):\n"
                     "  Sol/Sag ok     -> onceki/sonraki resim\n"
                     "  tekerlek       -> zoom\n"
                     "  Ctrl+tekerlek  -> dikey kaydirma\n"
                     "  Shift+tekerlek -> yatay kaydirma\n"
                     "  cift tik       -> grid view'a don\n\n"
                     "Kisayollar (grid view):\n"
                     "  tek tik        -> sadece sec\n"
                     "  cift tik       -> sec ve resmi ac\n"
                     "  tekerlek       -> dikey kaydirma\n"
                     "  Ctrl+tekerlek  -> kucuk resim boyutu",
                bg=Theme.BG_PANEL, fg=Theme.FG, font=FONT_NORMAL,
                justify=tk.LEFT).pack(anchor=tk.W, padx=8, pady=8)

    def _add_slider(self, parent, label, var_name, vmin, vmax, default, hint):
        """Slider + Spinbox ikilisi (v0.4.1, kullanici istegi).

        - Slider serbest ceker; deger yanindaki Spinbox'a yansir.
        - Spinbox oklari 0.05 adimla degeri degistirir; slider ve
          onizleme aninda guncellenir.
        - Kutuya elle deger yazilabilir (Return/odak kaybiyla onaylanir;
          '0,35' gibi virgullu giris ve sinir asimi tolere edilir,
          gecersiz giriste son gecerli degere donulur).
        """
        tk.Label(parent, text=label, bg=Theme.BG_PANEL, fg=Theme.FG,
                font=FONT_NORMAL, anchor=tk.W).pack(fill=tk.X, pady=(12, 2))

        row = tk.Frame(parent, bg=Theme.BG_PANEL)
        row.pack(fill=tk.X, pady=4)

        var = tk.DoubleVar(value=default)
        setattr(self, f"{var_name}_var", var)
        setattr(self, f"{var_name}_range", (vmin, vmax))

        spin_var = tk.StringVar(value=f"{default:.2f}")
        setattr(self, f"{var_name}_spin_var", spin_var)

        spin = tk.Spinbox(row, from_=vmin, to=vmax, increment=0.05, width=7,
                          textvariable=spin_var, font=FONT_NORMAL,
                          bg=Theme.BG_INPUT, fg=Theme.FG, relief=tk.FLAT,
                          buttonbackground=Theme.BG_HOVER,
                          buttonuprelief=tk.FLAT, buttondownrelief=tk.FLAT,
                          highlightthickness=0, bd=0, justify=tk.CENTER,
                          command=lambda n=var_name: self._on_slider_spin(n))
        spin.pack(side=tk.RIGHT, padx=(12, 0))
        spin.bind('<Return>', lambda e, n=var_name: self._on_slider_spin_entry(n))
        spin.bind('<FocusOut>', lambda e, n=var_name: self._on_slider_spin_entry(n))
        setattr(self, f"{var_name}_spin", spin)

        scale = tk.Scale(row, from_=vmin, to=vmax, orient=tk.HORIZONTAL,
                        variable=var, showvalue=False,
                        bg=Theme.BG_PANEL, fg=Theme.FG,
                        troughcolor=Theme.BG_INPUT, highlightthickness=0,
                        sliderrelief=tk.FLAT, activebackground=Theme.ACCENT_DARK,
                        resolution=0.01, font=FONT_SMALL,
                        command=lambda v, n=var_name: self._on_slider_change(n))
        # Sabit length kaldirildi: slider panelin tum genisligine yayilir
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        tk.Label(parent, text=hint, bg=Theme.BG_PANEL, fg=Theme.FG_MUTED,
                font=FONT_SMALL, anchor=tk.W, justify=tk.LEFT).pack(
                    fill=tk.X, pady=(2, 10))

    def _parse_slider_text(self, text, name):
        """'0,5' / '0.5' / ' 0.35 ' gibi girisi ayiklar; gecersizse None.

        Sinir degerlerin disina tasan giris kirpilir (kirpilan deger
        doner); tamamen sayi olmayan giris None dondurur."""
        try:
            v = float(str(text).strip().replace(',', '.'))
        except (ValueError, TypeError):
            return None
        vmin, vmax = getattr(self, f"{name}_range", (0.0, 1.0))
        return max(vmin, min(vmax, v))

    def _on_slider_spin(self, name):
        """Spinbox oklari (adim 0.05): degeri degiskene yaz, onizleyi guncelle."""
        v = self._parse_slider_text(getattr(self, f"{name}_spin_var").get(), name)
        if v is not None:
            getattr(self, f"{name}_var").set(v)
            self._on_slider_change(name)

    def _on_slider_spin_entry(self, name):
        """Elle giris (Return/odak kaybi): gecersizse son gecerli degere don."""
        v = self._parse_slider_text(getattr(self, f"{name}_spin_var").get(), name)
        if v is None:
            v = getattr(self, f"{name}_var").get()
        getattr(self, f"{name}_var").set(v)
        self._on_slider_change(name)

    def _on_slider_change(self, name):
        var = getattr(self, f"{name}_var")
        # Spinbox gosterimini slider ile senkron tut (dongusuz: Spinbox
        # programatik textvariable degisiminde command uretmez)
        getattr(self, f"{name}_spin_var").set(f"{var.get():.2f}")
        if self.preview_mode:
            self._schedule_live_preview()

    def _schedule_live_preview(self):
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(200, self._do_live_preview)

    def _do_live_preview(self):
        """Canli onizleme isci thread'i baslatir.

        Thread guvenligi: Tk degiskenleri SADECE main thread'de okunur;
        thread'e duz (plain) veri gecilir."""
        if not self.preview_mode:
            return
        params = self._snapshot_params()
        mevcut_yol = (self.image_list[self.current_image_idx]
                      if 0 <= self.current_image_idx < len(self.image_list)
                      else None)
        jobs = []
        for path in self.image_list:
            mappings = self._get_mappings_for(path)
            if mappings and path in self.image_arrays:
                jobs.append((path, list(mappings)))
            else:
                # Mapping yoksa eski preview kaldirilir
                self.preview_arrays.pop(path, None)
        if not jobs:
            self.root.after(0, self._refresh_current_view)
            return
        # Ekranda acik olan resim once hesaplansin (tam cozunurlukte
        # hesap yavas olabilir; kullanicinin gordugu resim ilk olsun)
        jobs.sort(key=lambda j: 0 if j[0] == mevcut_yol else 1)
        self._preview_gen += 1
        gen = self._preview_gen
        t = threading.Thread(target=self._recompute_all_previews,
                             args=(params, jobs, gen), daemon=True)
        t.start()

    def _snapshot_params(self):
        """Kaydirici degerlerini main thread'de okuyup duz sozluk dondurur."""
        return {
            'softness': self.softness_var.get(),
            'snap': self.snap_var.get(),
            'strength': self.strength_var.get(),
        }

    def _recompute_all_previews(self, params, jobs, gen):
        """Tum resimlerin onizlemesini arka planda hesapla (Tk'ye dokunmaz).

        gen: bu isi baslatan nesil sayaci. Is sirasinda kaydirici oynarsa
        nesil degisir ve eskimis hesap hicbir seye dokunmadan durur."""
        with self.preview_lock:
            total = len(jobs)
            for i, (path, mappings) in enumerate(jobs):
                if gen != self._preview_gen:
                    return  # Eskimis is: yenisi zaten yolda
                try:
                    warp = self._build_warp_from_lists(
                        [m["src"] for m in mappings],
                        [m["dst"] for m in mappings],
                        params)
                    preview_arr = self._compute_preview(
                        warp, path, params['strength'])
                    if preview_arr is not None:
                        self._store_preview(path, preview_arr)
                    self.root.after(0, lambda i=i, n=total:
                        self.status_var.set(
                            f"Onizleme hesaplaniyor {i+1}/{n}..."))
                except Exception as e:
                    print(f"Preview hatasi {path}: {e}")

            if gen == self._preview_gen:
                self.root.after(0, self._refresh_current_view)

    def _store_preview(self, path, arr):
        """Onizlemeyi kaydet. Tam cozunurluk kopyalar bellek yer: 12MP
        resim ~36MB. Bu yuzden en fazla 4 resim tutulur; en eskisi
        atilir (o resme tekrar girince yeniden hesaplanir)."""
        self.preview_arrays.pop(path, None)
        self.preview_arrays[path] = arr
        while len(self.preview_arrays) > 4:
            en_eski = next(iter(self.preview_arrays))
            self.preview_arrays.pop(en_eski)

    def _refresh_current_view(self):
        """Mevcut gorunum (grid veya tekil) guncelle."""
        if self.current_image_idx < 0:
            # Grid view'da mapping yapilanlar icin cerceve rengi guncelle
            self.show_grid()
            self.status_var.set("Onizleme guncellendi (grid view).")
        else:
            path = self.image_list[self.current_image_idx]
            if self.preview_mode and path in self.preview_arrays:
                self.preview_array = self.preview_arrays[path]
                self._display_array(self.preview_array)
                self.status_var.set(f"Onizleme: {path.name}")
            elif self.preview_mode:
                # Onizleme acik ama bu resmin hesabi yok (bellekten
                # atilmis): orijinali goster, arka planda yeniden hesapla
                if path in self.original_images:
                    self._display_image(self.original_images[path])
                self.status_var.set(f"Onizleme hesaplaniyor: {path.name}")
                self._schedule_live_preview()
            elif path in self.original_images:
                self._display_image(self.original_images[path])

    def _compute_preview(self, warp, path, strength):
        """TAM COZUNURLUKTE hesaplar.

        Eskiden hiz icin 800px'lik kopya uzerinden hesapliyordu; ama o
        zaman onizleme ekranda orijinalden farkli boyutta ciziliyor ve
        derin zoomda bulaniklasiyordu (kullanici raporu). Artik hesap
        orijinalin kendisi uzerinden yapilir: onizleme, kaydedilen
        sonucun piksel piksel aynisidir. Bedeli hizdir; is arka plan
        thread'inde yapildigi icin pencere donmaz."""
        arr = self.image_arrays.get(path)
        if arr is None:
            return None
        return warp.apply(arr, strength=strength)

    def on_batch_mode_change(self):
        # Modu degistirince eslesme listesini tazele
        self._refresh_mappings_list()

    # ============================================================
    # DOSYA YUKLEME
    # ============================================================

    def load_files(self):
        files = open_multiple_files(
            initial_dir=str(INPUT_DIR),
            file_types=[("Goruntuler", "*.jpg *.jpeg *.png *.bmp *.tiff *.webp")],
            title="Dosya(lar) sec")
        if not files:
            return
        self._add_files(files)

    def load_directory(self):
        folder = open_directory(initial_dir=str(INPUT_DIR), title="Klasor sec")
        if not folder:
            return
        # Klasordeki tum gorselleri bul
        valid_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.webp'}
        files = []
        for f in sorted(Path(folder).iterdir()):
            if f.is_file() and f.suffix.lower() in valid_exts:
                files.append(str(f))
        if not files:
            messagebox.showinfo("Bilgi", "Klasorde gorsel bulunamadi.")
            return
        self._add_files(files)

    def _add_files(self, file_paths):
        """Dosyalari yukle, input/ klasorune kopyala, grid view'a ekle.

        Ayni isimde dosya varsa 'isim (1)', 'isim (2)'... diye YENI kopya
        olusturulur; eskisi asla ezilmez. Bu oturumda kopyalanan her dosya
        session_files listesine yazilir ve program kapanirken temizlenir."""
        new_count = 0
        for fp in file_paths:
            src = Path(fp)
            # input/'a kopyala (ayni isim varsa sonuna (1), (2)... ekle)
            try:
                dest = INPUT_DIR / src.name
                if dest.exists():
                    n = 1
                    while True:
                        candidate = INPUT_DIR / f"{src.stem} ({n}){src.suffix}"
                        if not candidate.exists():
                            dest = candidate
                            break
                        n += 1
                shutil.copy2(src, dest)
                self.session_files.append(dest)
                target_path = dest
            except Exception as e:
                print(f"Kopyalama hatasi {fp}: {e}")
                target_path = src

            if target_path in self.image_list:
                continue
            try:
                img = Image.open(target_path).convert('RGB')
                self.original_images[target_path] = img
                self.image_arrays[target_path] = np.array(img)
                self.image_list.append(target_path)
                # Thumbnail olustur
                self._create_thumbnail(target_path, img)
                new_count += 1
            except Exception as e:
                print(f"Yukleme hatasi {fp}: {e}")

        if new_count > 0:
            self.status_var.set(f"{new_count} dosya yuklendi. Toplam: "
                                f"{len(self.image_list)} dosya.")
            # Grid view'i goster
            self.show_grid()
        else:
            self.status_var.set("Yeni dosya eklenmedi.")

    def _create_thumbnail(self, path, pil_image, size=None):
        """Verilen path icin thumbnail olustur ve kaydet."""
        if size is None:
            size = self.thumb_size_var
        thumb = pil_image.copy()
        thumb.thumbnail((size, size), Image.LANCZOS)
        self.thumbnails[path] = ImageTk.PhotoImage(thumb)

    def _recreate_all_thumbnails(self):
        """Tum thumbnail'lari thumb_size_var'a gore yeniden olustur."""
        for path, pil_img in self.original_images.items():
            self._create_thumbnail(path, pil_img)

    # ============================================================
    # GRID VIEW
    # ============================================================

    def show_grid(self):
        """Yuklenen tum resimleri grid view olarak goster."""
        # Eger preview_mode aciksa ve grid view gorunmuyorsa, sadece grid view'i goster
        # (preview_mode kapali olsun ama preview_arrays korunur)
        self.current_image_idx = -1
        self.canvas.delete("all")
        self.thumbnail_labels.clear()

        if not self.image_list:
            self.status_var.set("Hic dosya yuklu degil.")
            return

        # Grid yerlesimi: sutun sayisi canvas genisligine uyarlanir
        # (dosya yoneticisi gibi). Kucuk resim boyutu Ctrl+tekerlek ile
        # degistirilmedikce sabittir.
        thumb_size = self.thumb_size_var
        padding = 10
        cell_w = thumb_size + padding * 2
        cell_h = thumb_size + 30  # alttaki dosya adi icin pay
        canvas_w = self.canvas.winfo_width()
        if canvas_w <= 1:
            canvas_w = 900  # olcum alinamadiysa makul varsayim
        cols = max(1, int(canvas_w // cell_w))

        for i, path in enumerate(self.image_list):
            r, c = divmod(i, cols)
            x = c * cell_w + padding
            y = r * cell_h + padding

            # Cerceve mantigi:
            # - Eslesme varsa: kalin mavi dis cerceve
            # - Seciliyse: ince kirmizi ic cerceve mavinin icinde
            has_mapping = bool(self._get_mappings_for(path))
            is_selected = (path == self.selected_thumb)

            if has_mapping:
                outer_color = Theme.ACCENT
            else:
                outer_color = Theme.BG_LIST_ITEM

            # Dis cerceve (kalin - 4px)
            bg_rect = self.canvas.create_rectangle(
                x - 4, y - 4, x + thumb_size + 4, y + thumb_size + 4,
                fill=outer_color, outline='', tags=f'thumb_{i}')

            # Ic cerceve (ince - 2px, sadece seciliyse kirmizi)
            if is_selected:
                self.canvas.create_rectangle(
                    x - 2, y - 2, x + thumb_size + 2, y + thumb_size + 2,
                    fill='', outline=Theme.DANGER, width=2,
                    tags=f'inner_{i}')

            # Thumbnail
            photo = self.thumbnails.get(path)
            if photo:
                img_item = self.canvas.create_image(
                    x + thumb_size // 2, y + thumb_size // 2,
                    image=photo, tags=f'img_{i}')

            # Dosya adi
            name = path.name
            if len(name) > 24:
                name = name[:21] + '...'
            self.canvas.create_text(
                x + thumb_size // 2, y + thumb_size + 8,
                text=name, fill=Theme.FG_MUTED, font=FONT_SMALL,
                tags=f'name_{i}')

            # Baglama
            for tag in [f'img_{i}', f'thumb_{i}', f'name_{i}']:
                self.canvas.tag_bind(tag, '<Button-1>',
                    lambda e, p=path: self._on_thumb_click(p))
                self.canvas.tag_bind(tag, '<Double-Button-1>',
                    lambda e, p=path: self._on_thumb_double_click(p))

        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.zoom_factor = 1.0
        self._update_zoom_label()
        if self.preview_mode:
            self.nav_info.set(f"Grid view | ONIZLEME ACIK | {len(self.image_list)} resim")
        else:
            self.nav_info.set(f"Grid view | {len(self.image_list)} resim")

    def _on_thumb_click(self, path):
        """Tek tik: SADECE sec (acmaz). Resmi acmak icin cift tiklayin."""
        old_selected = self.selected_thumb
        self.selected_thumb = path

        # Onceki seciliyi guncelle
        if old_selected is not None and old_selected != path and old_selected in self.image_list:
            old_idx = self.image_list.index(old_selected)
            self._update_thumb_color(old_idx, old_selected)

        # Yeni seciliyi guncelle (kirmizi cerceve)
        if path in self.image_list:
            new_idx = self.image_list.index(path)
            self._update_thumb_color(new_idx, path, is_selected=True)
            self.status_var.set(f"Secildi: {path.name}  (acmak icin cift tik)")

    def _update_thumb_color(self, idx, path, is_selected=False):
        """Tek bir thumbnail'in cercevesini guncelle (iki katmanli)."""
        items = self.canvas.find_withtag(f'thumb_{idx}')
        if not items:
            return
        outer_rect = items[0]

        has_mapping = bool(self._get_mappings_for(path))
        if has_mapping:
            outer_color = Theme.ACCENT
        else:
            outer_color = Theme.BG_LIST_ITEM
        self.canvas.itemconfig(outer_rect, fill=outer_color)

        # Ic cerceveyi sil
        old_inner = self.canvas.find_withtag(f'inner_{idx}')
        for item in old_inner:
            self.canvas.delete(item)

        if is_selected:
            coords = self.canvas.coords(outer_rect)
            if len(coords) >= 4:
                x1, y1, x2, y2 = coords[:4]
                self.canvas.create_rectangle(
                    x1 + 2, y1 + 2, x2 - 2, y2 - 2,
                    fill='', outline=Theme.DANGER, width=2,
                    tags=f'inner_{idx}')

    def _on_thumb_double_click(self, path):
        """Cift tik: sec ve resmi ac.

        Not: cift tik ayni zamanda iki kez tek tik da uretir; tek tik artik
        sadece secim yaptigi icin acma islemi guvenle burada yapilir.

        Zaman damgasi: resim acildiktan hemen sonra widget seviyesindeki
        <Double-Button-1> de tetiklenir; o talimat 'grid'e don' oldugu icin
        resmi aninda kapatirdi. on_canvas_double_click bu damgaya bakip
        yok sayar."""
        if path not in self.image_list:
            return
        self._last_thumb_open = time.monotonic()
        self.selected_thumb = path
        idx = self.image_list.index(path)
        self._update_thumb_color(idx, path, is_selected=True)
        self._open_image_at(idx)

    def _open_image_at(self, idx):
        """Verilen indeksteki resmi tam ekran ac."""
        if idx < 0 or idx >= len(self.image_list):
            return
        self.current_image_idx = idx
        path = self.image_list[idx]
        self.zoom_factor = 1.0
        # Eger preview_mode aciksa ve bu resim icin preview varsa onu goster
        if self.preview_mode and path in self.preview_arrays:
            self.preview_array = self.preview_arrays[path]
            self._display_array(self.preview_array)
            self.status_var.set(f"Onizleme: {path.name}")
        elif self.preview_mode:
            # Onizleme acik ama bu resmin hesabi bellekten atilmis:
            # once orijinal goster, arka planda yeniden hesapla
            self.preview_array = None
            self._display_image(self.original_images[path])
            self.status_var.set(f"Onizleme hesaplaniyor: {path.name}")
            self._schedule_live_preview()
        else:
            self.preview_array = None
            self._display_image(self.original_images[path])
            self.status_var.set(f"Acik: {path.name}")
        self.nav_info.set(f"{idx+1} / {len(self.image_list)}")
        # Mapping listesini guncelle
        self._refresh_mappings_list()

    def prev_image(self):
        if self.current_image_idx > 0:
            self._open_image_at(self.current_image_idx - 1)

    def next_image(self):
        if 0 <= self.current_image_idx < len(self.image_list) - 1:
            self._open_image_at(self.current_image_idx + 1)

    # ============================================================
    # GORUNTULEME
    # ============================================================

    def _display_image(self, pil_image):
        """Goruntuyu canvas'ta goster. Hiz icin BILINEAR kullanir."""
        canvas_w = max(self.canvas.winfo_width(), 600)
        canvas_h = max(self.canvas.winfo_height(), 400)
        w, h = pil_image.size
        base = min(canvas_w / w, canvas_h / h, 1.0)
        self.base_scale = base
        total = base * self.zoom_factor
        new_w, new_h = max(int(w * total), 1), max(int(h * total), 1)
        # BILINEAR cok daha hizli (LANCZOS yavasti)
        resized = pil_image.resize((new_w, new_h), Image.BILINEAR)
        self.display_photo = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.display_photo)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self._update_zoom_label()

    def _display_array(self, arr):
        self._display_image(Image.fromarray(arr))

    def _update_zoom_label(self):
        pct = int(self.zoom_factor * 100)
        self.zoom_var.set(f"Zoom: {pct}%")

    def toggle_preview(self):
        """'Onizle' tusu (Secenek A):

        - Kapaliyken basilinca islemeyi BASLATIR ve sonucu gosterir. Bu
          andan itibaren kaydirici degisiklikleri canli yansir.
        - Acikken basilinca kapanir ve orijinal gosterilir.

        Onizle basilmadan HICBIR SEY otomatik hesaplanmaz (P3)."""
        if not self.image_list:
            messagebox.showwarning("Uyari", "Once dosya yukleyin.")
            return

        # En az bir resimde mapping olmali
        has_any = False
        for path in self.image_list:
            if self._get_mappings_for(path):
                has_any = True
                break
        if not has_any:
            messagebox.showwarning("Uyari",
                "Hic eslesme yok. Once birkac nokta secin.")
            return

        if self.preview_mode:
            # Kapat - orijinali goster
            self.preview_mode = False
            self.preview_btn.config(text="Onizle")
            self._refresh_current_view()
            self.status_var.set("Onizleme kapandi (orijinal gosteriliyor).")
        else:
            # Ac - tum resimler icin hesapla
            self.preview_mode = True
            self.preview_btn.config(text="Onizlemeyi Kapat")
            self.status_var.set("Onizleme acik - hesaplaniyor...")
            self._schedule_live_preview()

    # ============================================================
    # ZOOM / SCROLL
    # ============================================================

    def on_mouse_wheel(self, event):
        if self.current_image_idx < 0:
            # Grid view: tekerlek = dikey kaydirma (zoom degil)
            self._scroll_v(-2 if event.delta > 0 else 2)
            return
        self._zoom_at(event.x, event.y, 1.15 if event.delta > 0 else 0.87)

    def on_wheel_button_4(self, event):
        """Linux tekerlek yukari: grid'de kaydir, tekil goruntude zoom."""
        if self.current_image_idx < 0:
            self._scroll_v(-2)
        else:
            self._zoom_at(event.x, event.y, 1.25)

    def on_wheel_button_5(self, event):
        """Linux tekerlek asagi: grid'de kaydir, tekil goruntude zoom."""
        if self.current_image_idx < 0:
            self._scroll_v(2)
        else:
            self._zoom_at(event.x, event.y, 0.8)

    def _on_canvas_resize(self, event):
        """Canvas boyutu degistince grid sutunlarini uyarla (debounce'lu)."""
        if self.current_image_idx >= 0:
            return
        if self._grid_job is not None:
            self.root.after_cancel(self._grid_job)
        self._grid_job = self.root.after(150, self._relayout_grid)

    def _relayout_grid(self):
        self._grid_job = None
        if self.current_image_idx < 0 and self.image_list:
            self.show_grid()

    def on_ctrl_wheel(self, event):
        """Ctrl + tekerlek:
        - Grid view'da (current_image_idx < 0): thumbnail boyutunu degistir
        - Tekil goruntude: dikey scroll
        """
        if self.current_image_idx < 0:
            # Grid view - thumbnail boyutu
            if event.delta > 0:
                self.thumb_size_var = min(400, self.thumb_size_var + 20)
            else:
                self.thumb_size_var = max(80, self.thumb_size_var - 20)
            # Thumbnail'lari yeniden olustur
            self._recreate_all_thumbnails()
            self.show_grid()
            self.status_var.set(f"Thumbnail boyutu: {self.thumb_size_var}px")
        else:
            # Tekil goruntu - dikey scroll
            if event.delta > 0:
                self._scroll_v(-2)
            else:
                self._scroll_v(2)

    def _on_ctrl_button_4(self, event):
        """Linux: Ctrl + tekerlek yukari."""
        if self.current_image_idx < 0:
            self.thumb_size_var = min(400, self.thumb_size_var + 20)
            self._recreate_all_thumbnails()
            self.show_grid()
            self.status_var.set(f"Thumbnail boyutu: {self.thumb_size_var}px")
        else:
            self._scroll_v(-2)

    def _on_ctrl_button_5(self, event):
        """Linux: Ctrl + tekerlek asagi."""
        if self.current_image_idx < 0:
            self.thumb_size_var = max(80, self.thumb_size_var - 20)
            self._recreate_all_thumbnails()
            self.show_grid()
            self.status_var.set(f"Thumbnail boyutu: {self.thumb_size_var}px")
        else:
            self._scroll_v(2)

    def on_shift_wheel(self, event):
        """Shift + tekerlek = yatay scroll."""
        if event.delta > 0:
            self._scroll_h(-2)
        else:
            self._scroll_h(2)

    def _scroll_v(self, direction):
        self.canvas.yview_scroll(direction, "units")

    def _scroll_h(self, direction):
        self.canvas.xview_scroll(direction, "units")

    def _zoom_at(self, x, y, factor):
        """Verilen canvas koordinatina dogru zoom yap."""
        if self.current_image_idx < 0:
            return

        # Once mevcut scroll pozisyonunu ve fare konumunu kaydet
        old_zoom = self.zoom_factor
        try:
            old_x_view = self.canvas.xview()[0]
            old_y_view = self.canvas.yview()[0]
        except Exception:
            old_x_view = 0
            old_y_view = 0

        # Fare konumu canvas koordinatinda
        cx = self.canvas.canvasx(x)
        cy = self.canvas.canvasy(y)

        # Fare konumu toplam genisligin yuzdesi olarak
        scrollregion = self.canvas.cget('scrollregion').split()
        try:
            sr_w = float(scrollregion[2])
            sr_h = float(scrollregion[3])
        except (IndexError, ValueError):
            sr_w = 1
            sr_h = 1
        if sr_w <= 0 or sr_h <= 0:
            return

        # Fare konumu orijinal (zoomlanmamis) koordinatlarda
        # cx = orig_x * total_scale_old, oyleyse orig_x = cx / total_scale_old
        total_old = self.base_scale * old_zoom
        if total_old <= 0:
            return
        orig_x = cx / total_old
        orig_y = cy / total_old

        # Yeni zoom
        new_zoom = max(0.1, min(10.0, old_zoom * factor))
        if new_zoom == old_zoom:
            return
        self.zoom_factor = new_zoom

        # Goruntuyu yeniden ciz
        if self.preview_mode and self.preview_array is not None:
            self._display_array(self.preview_array)
        else:
            path = self.image_list[self.current_image_idx]
            self._display_image(self.original_images[path])

        # Yeni scroll pozisyonu: fare ayni orijinal noktayi gosteriyor olsun
        total_new = self.base_scale * new_zoom
        new_cx = orig_x * total_new
        new_cy = orig_y * total_new

        # Yeni scrollregion
        new_sr = self.canvas.cget('scrollregion').split()
        try:
            new_sr_w = float(new_sr[2])
            new_sr_h = float(new_sr[3])
        except (IndexError, ValueError):
            new_sr_w = 1
            new_sr_h = 1

        # Fare konumu pencerede sabit kalmali:
        # canvas'ta fare x = (new_cx - xview_offset) konumunda
        # xview_offset = new_cx - fare_x_pencere
        # xview fraction = xview_offset / new_sr_w
        if new_sr_w > 0 and new_sr_h > 0:
            fare_x_pencere = x
            fare_y_pencere = y
            new_xview = max(0, (new_cx - fare_x_pencere) / new_sr_w)
            new_yview = max(0, (new_cy - fare_y_pencere) / new_sr_h)
            self.canvas.xview_moveto(new_xview)
            self.canvas.yview_moveto(new_yview)

    # ============================================================
    # DAMLALIK
    # ============================================================

    def on_canvas_click(self, event):
        if self.current_image_idx < 0:
            return
        path = self.image_list[self.current_image_idx]
        arr = self.image_arrays.get(path)
        if arr is None:
            return

        # Damlalik: onizleme aciksa once KAPAT, orijinal goster.
        # Renk secimi hep orijinal goruntu uzerinden yapilir.
        if self.preview_mode:
            self.preview_mode = False
            self.preview_btn.config(text="Onizle")
            self._display_image(self.original_images[path])
            self.status_var.set("Onizleme kapandi - orijinal uzerinden renk secin.")

        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        total_scale = self.base_scale * self.zoom_factor
        ox = int(cx / total_scale)
        oy = int(cy / total_scale)
        H, W = arr.shape[:2]
        if not (0 <= ox < W and 0 <= oy < H):
            return
        pixel = arr[oy, ox]
        rgb = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
        self._set_source_color(rgb, from_image=True, pos=(ox, oy))

    def on_canvas_double_click(self, event):
        """Cift tikla: tekil goruntuden grid view'a don.

        DIKKAT: Widget-seviyesi bu baglama, canvas item baglamalarindan
        SONRA tetiklenir. Grid view'da thumbnail uzerine cift tik item
        baglamasindan resmi ACAR; burada grid'e donseydik resim acilip
        ANINDA kapanirdi (bildirilen hata). Bu yuzden thumbnail acilisini
        takip eden kisa surede bu talimat yok sayilir.

        Sira bagimsizlik: bazi Tk surumlerinde sir ters donerse
        (widget once) current_image_idx henuz -1'dir ve islem zaten
        etkisiz kalir; sonra item baglamasi resmi acar. Iki durumda da
        nihai davranis dogrudur."""
        son_acilis = getattr(self, '_last_thumb_open', 0.0)
        if time.monotonic() - son_acilis < 0.2:
            return
        if self.current_image_idx >= 0:
            self.show_grid()

    def on_canvas_motion(self, event):
        if self.current_image_idx < 0:
            return
        path = self.image_list[self.current_image_idx]
        arr = self.image_arrays.get(path)
        if arr is None:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        total_scale = self.base_scale * self.zoom_factor
        ox = int(cx / total_scale)
        oy = int(cy / total_scale)
        H, W = arr.shape[:2]
        if not (0 <= ox < W and 0 <= oy < H):
            return
        pixel = arr[oy, ox]
        rgb = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
        hex_c = '#%02x%02x%02x' % rgb
        fg = 'white' if sum(rgb) < 384 else 'black'
        self.hover_label.config(text=f"  RGB {rgb}  ", bg=hex_c, fg=fg)

    def _set_source_color(self, rgb, from_image=False, pos=None):
        self.picked_source = rgb
        hex_c = '#%02x%02x%02x' % rgb
        self.source_swatch.config(bg=hex_c)
        if from_image and pos:
            self.source_rgb_var.set(
                f"RGB: {rgb}\nKonum: ({pos[0]}, {pos[1]})\n-> Paletten hedef sec")
        else:
            self.source_rgb_var.set(
                f"RGB: {rgb}\n(Elle ayarlandi)\n-> Paletten hedef sec")
        for i, v in enumerate(rgb):
            self.src_rgb_vars[i].set(v)
        self.status_var.set(f"Kaynak secildi: {rgb}")

    def _on_src_rgb_change(self, idx):
        try:
            r = self.src_rgb_vars[0].get()
            g = self.src_rgb_vars[1].get()
            b = self.src_rgb_vars[2].get()
        except tk.TclError:
            return
        rgb = (r, g, b)
        self.picked_source = rgb
        hex_c = '#%02x%02x%02x' % rgb
        self.source_swatch.config(bg=hex_c)
        self.source_rgb_var.set(f"RGB: {rgb}\n(Elle ayarlandi)\n-> Paletten hedef sec")

    def _on_src_rgb_spin(self, idx):
        self._on_src_rgb_change(idx)

    def _use_rgb_as_source(self):
        try:
            r = self.src_rgb_vars[0].get()
            g = self.src_rgb_vars[1].get()
            b = self.src_rgb_vars[2].get()
        except tk.TclError:
            messagebox.showerror("Hata", "Gecersiz RGB degeri.")
            return
        self._set_source_color((r, g, b), from_image=False)

    # ============================================================
    # PALET
    # ============================================================

    def _setup_default_palette(self):
        default = [
            (0,0,0), (64,64,64), (128,128,128), (192,192,192), (255,255,255),
            (255,0,0), (255,128,0), (255,255,0), (128,255,0), (0,255,0),
            (0,255,128), (0,255,255), (0,128,255), (0,0,255), (128,0,255),
            (255,0,255), (255,0,128), (128,64,0), (200,160,120), (255,220,180),
        ]
        for c in default:
            self.palette.append(c)
        self._render_palette()

    def _on_palette_resize(self, event):
        """Palet kutusu boyut degistirince: ic cerceve genisligini ayarla +
        genislik degistiyse sutun sayisini guncelle (debounce'lu)."""
        self.palette_canvas.itemconfig(self.palette_window_id, width=event.width)
        if self._palette_job is not None:
            self.root.after_cancel(self._palette_job)
        self._palette_job = self.root.after(150, self._palette_relayout)

    def _palette_relayout(self):
        """Genislik degistiyse paleti yeni sutun sayisiyla yeniden diz."""
        self._palette_job = None
        if not self.palette:
            return
        pal_w = self.palette_canvas.winfo_width()
        cols = max(1, pal_w // 62) if pal_w > 1 else 5
        if cols != self._palette_cols:
            self._render_palette()

    def _render_palette(self):
        for sw in self.palette_swatches:
            sw.destroy()
        self.palette_swatches.clear()
        # v0.4.1: sutun sayisi paletin gorunen genisligine uyarlanir
        # (grid view ile ayni mantik). Hucre genisligi = kare (56px) + padx (3+3) = 62
        pal_w = self.palette_canvas.winfo_width()
        if pal_w and pal_w > 1:
            cols = max(1, pal_w // 62)
        else:
            cols = 5  # olcum alinamadiysa eski sabit deger
        self._palette_cols = cols
        for i, color in enumerate(self.palette):
            r, c = divmod(i, cols)
            hex_c = '#%02x%02x%02x' % color
            # Frame kullan: width/height piksel olarak verilir -> kare
            sw = tk.Frame(self.palette_inner, bg=hex_c, width=56, height=56,
                         bd=0, highlightbackground=Theme.SWATCH_BORDER,
                         highlightthickness=1, cursor='hand2')
            sw.grid(row=r, column=c, padx=3, pady=3)
            sw.bind('<Button-1>', lambda e, c=color: self.on_palette_click(c))
            sw.bind('<Button-3>', lambda e, c=color: self._show_color_info(c))
            sw.bind('<Enter>', lambda e, w=sw: w.config(
                highlightbackground=Theme.ACCENT, highlightthickness=2))
            sw.bind('<Leave>', lambda e, w=sw: w.config(
                highlightbackground=Theme.SWATCH_BORDER, highlightthickness=1))
            sw.grid_propagate(False)
            self.palette_swatches.append(sw)
        for c in range(cols):
            self.palette_inner.columnconfigure(c, weight=0)
        self.palette_info_var.set(f"{len(self.palette)} renk")
        # Tekerlek destegi (v0.4.1): cocuk renk kartlari olayi yuttugu icin
        # agacin tamamina baglanir
        self._bind_mousewheel_vertical(self.palette_canvas, self.palette_inner)

    def _wheel_scroll(self, canvas, event):
        """Tekerlek olayini dikey kaydirmaya cevirir (v0.4.1).

        Linux (Pop!_OS dahil): Button-4 yukari, Button-5 asagi (X11'de
        num=4/5 garantidir). Windows/macOS: <MouseWheel>, delta +/-.
        Ayrica not: Tk'nin event_generate'i Button-5 desenini num=9 ile
        uretir; bu yuzden birim testler _wheel_scroll'i dogrudan cagirir."""
        yukari = (getattr(event, 'num', None) == 4 or
                  getattr(event, 'delta', 0) > 0)
        asagi = (getattr(event, 'num', None) == 5 or
                 getattr(event, 'delta', 0) < 0)
        if yukari:
            canvas.yview_scroll(-2, 'units')
        elif asagi:
            canvas.yview_scroll(2, 'units')

    def _bind_mousewheel_vertical(self, canvas, widget):
        """Tekerlekle dikey kaydirma: canvas + widget agacinin TUM uyelerine
        baglanir (cocuk widget'lar tekerlek olayini yuttugu icin recursive
        baglama gerekir).

        Windows/macOS: <MouseWheel> (delta +/-)
        Linux (Pop!_OS dahil): <Button-4> yukari, <Button-5> asagi"""
        hedefler = [canvas, widget]
        kuyruk = list(widget.winfo_children())
        while kuyruk:
            w = kuyruk.pop()
            hedefler.append(w)
            kuyruk.extend(w.winfo_children())
        for hedef in hedefler:
            for seq in ('<MouseWheel>', '<Button-4>', '<Button-5>'):
                hedef.bind(seq, lambda e, c=canvas: self._wheel_scroll(c, e))

    def on_palette_click(self, color):
        if self.picked_source is None:
            messagebox.showinfo("Bilgi",
                "Once kaynak renk secin (gorsele tikla veya RGB ayarla).")
            return
        if self.current_image_idx < 0 and self.batch_mode.get() == 'per_image':
            messagebox.showinfo("Bilgi",
                "Once bir resim acin (cift tik) veya 'Tum resimlere ayni' moduna gecin.")
            return

        # Mapping listesini belirle
        if self.batch_mode.get() == 'all_same':
            mapping_list = self.shared_mappings
        else:
            path = self.image_list[self.current_image_idx]
            if path not in self.mappings:
                self.mappings[path] = []
            mapping_list = self.mappings[path]

        # Ayni kaynak renk icin zaten eslesme var mi? -> Vazgec / Degistir
        existing = None
        for m in mapping_list:
            if tuple(m["src"]) == tuple(self.picked_source):
                existing = m
                break

        if existing is not None:
            if not self._ask_replace_same_source(existing, color):
                return  # Vazgec
        else:
            mapping_list.append({"src": self.picked_source, "dst": color})

        self._refresh_mappings_list()

        # Otomatik isleme YOK (P3): onizleme kapaliysa kullanici 'Onizle'yi
        # basar. Aciksa (Secenek A) degisiklik canli yansir.
        if self.preview_mode:
            self._schedule_live_preview()
            self.status_var.set("Eslesme degisti - onizleme guncelleniyor.")
        else:
            self.status_var.set("Eslesme eklendi. Gormek icin 'Onizle'ye basin.")

        # Kaynak secimi temizle
        self.picked_source = None
        self.source_swatch.config(bg='#808080')
        self.source_rgb_var.set("Henuz secilmedi\n(gorsele tikla veya asagidan ayarla)")

    def _ask_replace_same_source(self, existing, new_color):
        """Ayni kaynak renk zaten eslesmis: Vazgec / Degistir diyalogu."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Ayni kaynak renk")
        dlg.configure(bg=Theme.BG_PANEL)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)

        src_hex = '#%02x%02x%02x' % tuple(existing["src"])
        old_hex = '#%02x%02x%02x' % tuple(existing["dst"])
        new_hex = '#%02x%02x%02x' % tuple(new_color)

        tk.Label(dlg, text="Bu kaynak renk icin zaten bir eslesme var.",
                 bg=Theme.BG_PANEL, fg=Theme.FG,
                 font=FONT_NORMAL).pack(padx=24, pady=(18, 10))

        row = tk.Frame(dlg, bg=Theme.BG_PANEL)
        row.pack(padx=24, pady=4)
        tk.Label(row, bg=src_hex, width=6, height=2, relief=tk.SOLID,
                 bd=1).pack(side=tk.LEFT, padx=4)
        tk.Label(row, text="->", bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                 font=FONT_LARGE).pack(side=tk.LEFT, padx=4)
        tk.Label(row, bg=old_hex, width=6, height=2, relief=tk.SOLID,
                 bd=1).pack(side=tk.LEFT, padx=4)
        tk.Label(row, text="  yerine  ", bg=Theme.BG_PANEL, fg=Theme.FG_MUTED,
                 font=FONT_SMALL).pack(side=tk.LEFT, padx=4)
        tk.Label(row, bg=new_hex, width=6, height=2, relief=tk.SOLID,
                 bd=1).pack(side=tk.LEFT, padx=4)

        sonuc = {'degistir': False}
        btns = tk.Frame(dlg, bg=Theme.BG_PANEL)
        btns.pack(pady=14)

        def on_degistir():
            sonuc['degistir'] = True
            dlg.destroy()

        tk.Button(btns, text="Degistir", bg=Theme.ACCENT, fg=Theme.BG,
                  font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=6,
                  activebackground=Theme.ACCENT_DARK, activeforeground=Theme.BG,
                  command=on_degistir).pack(side=tk.LEFT, padx=4)
        tk.Button(btns, text="Vazgec", bg=Theme.BG_INPUT, fg=Theme.FG,
                  font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=6,
                  activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                  command=dlg.destroy).pack(side=tk.LEFT, padx=4)

        dlg.wait_window()

        if sonuc['degistir']:
            existing["dst"] = tuple(new_color)
            return True
        return False

    def _show_color_info(self, color):
        messagebox.showinfo("Renk Bilgisi",
                           f"RGB: {color}\nHEX: #%02x%02x%02x" % color)

    def add_color_manual(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Renk Ekle")
        dlg.geometry("340x280")
        dlg.transient(self.root)
        dlg.configure(bg=Theme.BG_PANEL)

        tk.Label(dlg, text="Yeni palet rengi ekle", bg=Theme.BG_PANEL,
                fg=Theme.ACCENT, font=FONT_LARGE).pack(pady=10)

        entries = []
        for ch in ['R', 'G', 'B']:
            row = tk.Frame(dlg, bg=Theme.BG_PANEL)
            row.pack(pady=4, padx=20, fill=tk.X)
            tk.Label(row, text=ch, bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                    font=FONT_NORMAL, width=2).pack(side=tk.LEFT)
            e = tk.Entry(row, width=8, font=FONT_NORMAL, bg=Theme.BG_INPUT,
                        fg=Theme.FG, insertbackground=Theme.FG, relief=tk.FLAT,
                        highlightthickness=1, highlightbackground=Theme.BORDER)
            e.pack(side=tk.LEFT, padx=8)
            entries.append(e)

        preview = tk.Label(dlg, bg='#808080', width=14, height=3, relief=tk.SOLID,
                          bd=1, highlightbackground=Theme.SWATCH_BORDER,
                          highlightthickness=1)
        preview.pack(pady=8)

        def upd(_=None):
            try:
                vals = [int(e.get()) for e in entries]
                if all(0 <= v <= 255 for v in vals):
                    preview.config(bg='#%02x%02x%02x' % tuple(vals))
            except ValueError:
                pass
        for e in entries:
            e.bind('<KeyRelease>', upd)

        def on_ok():
            try:
                vals = [int(e.get()) for e in entries]
                if not all(0 <= v <= 255 for v in vals):
                    raise ValueError()
                self.palette.append(tuple(vals))
                self._render_palette()
                dlg.destroy()
            except ValueError:
                messagebox.showerror("Hata", "0-255 arasi sayi girin.", parent=dlg)

        btns = tk.Frame(dlg, bg=Theme.BG_PANEL)
        btns.pack(pady=8)
        tk.Button(btns, text="Ekle", bg=Theme.ACCENT, fg=Theme.BG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=6,
                 activebackground=Theme.ACCENT_DARK, activeforeground=Theme.BG,
                 command=on_ok).pack(side=tk.LEFT, padx=4)
        tk.Button(btns, text="Iptal", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=6,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=dlg.destroy).pack(side=tk.LEFT, padx=4)

    def clear_palette(self):
        if messagebox.askyesno("Onay", "Paleti temizlemek istediginize emin misiniz?"):
            self.palette.clear()
            self._render_palette()

    def open_palette_from_image(self):
        """Gorsel yukle, uzerine tiklayarak palet renkleri olustur.

        Her tiklanan pikselin rengi palete eklenir (ayni renk tek kez)."""
        path = open_file(
            initial_dir=str(APP_DIR),
            file_types=[("Goruntuler", "*.jpg *.jpeg *.png *.bmp *.tiff *.webp")],
            title="Palet cikarilacak gorseli sec")
        if not path:
            return
        try:
            pil = Image.open(path).convert('RGB')
        except Exception as e:
            messagebox.showerror("Hata", f"Gorsel acilamadi:\n{e}")
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Gorselden Palet Olustur")
        dlg.configure(bg=Theme.BG_PANEL)
        dlg.transient(self.root)

        tk.Label(dlg, text="Gorsel uzerine tikla -> o renk palete eklenir",
                 bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                 font=FONT_NORMAL).pack(pady=(12, 6))

        max_box = 480
        scale = min(max_box / max(pil.width, 1), max_box / max(pil.height, 1), 1.0)
        disp_w = max(1, int(pil.width * scale))
        disp_h = max(1, int(pil.height * scale))
        disp = pil.resize((disp_w, disp_h), Image.BILINEAR)
        photo = ImageTk.PhotoImage(disp)

        cnv = tk.Canvas(dlg, width=disp_w, height=disp_h, highlightthickness=1,
                        highlightbackground=Theme.BORDER, cursor='crosshair')
        cnv.pack(padx=12, pady=6)
        cnv.create_image(0, 0, anchor=tk.NW, image=photo)
        cnv.image_ref = photo  # referans tutulmazsa resim gorunmez olur

        info_var = tk.StringVar(value=f"Palet: {len(self.palette)} renk")
        tk.Label(dlg, textvariable=info_var, bg=Theme.BG_PANEL,
                 fg=Theme.FG_MUTED, font=FONT_SMALL).pack(pady=(4, 2))

        last = tk.Label(dlg, bg='#808080', width=12, height=2,
                        relief=tk.SOLID, bd=1)
        last.pack(pady=(0, 8))

        def on_pick(event):
            ix = min(max(int(event.x / scale), 0), pil.width - 1)
            iy = min(max(int(event.y / scale), 0), pil.height - 1)
            rgb = pil.getpixel((ix, iy))
            rgb = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
            if rgb not in self.palette:
                self.palette.append(rgb)
                self._render_palette()
            info_var.set(f"Palet: {len(self.palette)} renk  (eklendi: RGB {rgb})")
            last.config(bg='#%02x%02x%02x' % rgb)

        cnv.bind('<Button-1>', on_pick)

        tk.Button(dlg, text="Kapat", bg=Theme.BG_INPUT, fg=Theme.FG,
                  font=FONT_BUTTON, relief=tk.FLAT, padx=14, pady=6,
                  activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                  command=dlg.destroy).pack(pady=(0, 12))

    def load_palette_gpl(self):
        path = open_file(
            initial_dir=str(PALETTES_DIR),
            file_types=[("GIMP Palette", "*.gpl")],
            title="Palet sec")
        if not path:
            return
        try:
            colors = []
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith(('GIMP', 'Name:', 'Columns:', '#')):
                        continue
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            colors.append((int(parts[0]), int(parts[1]), int(parts[2])))
                        except ValueError:
                            continue
            if not colors:
                messagebox.showwarning("Uyari", "Palet dosyasinda renk bulunamadi.")
                return
            self.palette = colors
            self._render_palette()
            self.status_var.set(f"Palet yuklendi: {len(colors)} renk.")
        except Exception as e:
            messagebox.showerror("Hata", f"Palet yuklenemedi:\n{e}")

    def save_palette_gpl(self):
        path = save_file(
            initial_dir=str(PALETTES_DIR),
            default_name="my_palette.gpl",
            file_types=[("GIMP Palette", "*.gpl")],
            title="Palet kaydet")
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("GIMP Palette\n")
                f.write(f"Name: {Path(path).stem}\nColumns: 5\n#\n")
                for c in self.palette:
                    f.write(f"{c[0]:3d} {c[1]:3d} {c[2]:3d}\tUntitled\n")
            self.status_var.set(f"Palet kaydedildi: {path}")
        except Exception as e:
            messagebox.showerror("Hata", f"Palet kaydedilemedi:\n{e}")

    # ============================================================
    # ESLESME LISTESI
    # ============================================================

    def _get_mappings_for(self, path):
        """Verilen path icin gecerli mappings listesini dondur."""
        if self.batch_mode.get() == 'all_same':
            return self.shared_mappings
        return self.mappings.get(path, [])

    def _refresh_mappings_list(self):
        for w in self.list_inner.winfo_children():
            w.destroy()

        if self.batch_mode.get() == 'all_same':
            current = self.shared_mappings
            title_prefix = "[Tum resimler] "
        elif self.current_image_idx >= 0:
            path = self.image_list[self.current_image_idx]
            current = self.mappings.get(path, [])
            title_prefix = f"[{path.name[:20]}] "
        else:
            current = []
            title_prefix = ""

        if not current:
            tk.Label(self.list_inner, text="Henuz eslesme yok",
                    bg=Theme.BG_PANEL, fg=Theme.FG_MUTED, font=FONT_SMALL).pack(
                        pady=10)
            self._bind_mousewheel_vertical(self.list_canvas, self.list_inner)
            return

        for i, m in enumerate(current):
            row = self._build_mapping_row(self.list_inner, i, m)
            row.pack(fill=tk.X, padx=2, pady=2)
        # Satirlar yeniden yaratildi: tekerlek baglamalarini tazele (v0.4.1)
        self._bind_mousewheel_vertical(self.list_canvas, self.list_inner)

    def _build_mapping_row(self, parent, idx, mapping):
        row = tk.Frame(parent, bg=Theme.BG_LIST_ITEM, bd=0,
                      highlightbackground=Theme.BORDER, highlightthickness=1)
        src = mapping["src"]
        dst = mapping["dst"]
        src_hex = '#%02x%02x%02x' % src
        dst_hex = '#%02x%02x%02x' % dst

        tk.Label(row, bg=src_hex, width=5, height=3, relief=tk.FLAT,
                highlightbackground=Theme.SWATCH_BORDER,
                highlightthickness=1).pack(side=tk.LEFT, padx=6, pady=6)
        tk.Label(row, text=f"{src}", bg=Theme.BG_LIST_ITEM, fg=Theme.FG,
                font=FONT_SMALL, width=14).pack(side=tk.LEFT, padx=2)

        tk.Label(row, text=" -> ", bg=Theme.BG_LIST_ITEM, fg=Theme.ACCENT,
                font=FONT_LARGE).pack(side=tk.LEFT, padx=4)

        tk.Label(row, bg=dst_hex, width=5, height=3, relief=tk.FLAT,
                highlightbackground=Theme.SWATCH_BORDER,
                highlightthickness=1).pack(side=tk.LEFT, padx=6, pady=6)
        tk.Label(row, text=f"{dst}", bg=Theme.BG_LIST_ITEM, fg=Theme.FG,
                font=FONT_SMALL, width=14).pack(side=tk.LEFT, padx=2)

        tk.Button(row, text="X", bg=Theme.DANGER, fg=Theme.BG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=8, pady=4,
                 activebackground='#c46a82', activeforeground=Theme.BG,
                 command=lambda i=idx: self._delete_mapping_by_idx(i)).pack(
                     side=tk.RIGHT, padx=6, pady=6)

        return row

    def _delete_mapping_by_idx(self, idx):
        if self.batch_mode.get() == 'all_same':
            if 0 <= idx < len(self.shared_mappings):
                del self.shared_mappings[idx]
        else:
            if self.current_image_idx < 0:
                return
            path = self.image_list[self.current_image_idx]
            if path in self.mappings and 0 <= idx < len(self.mappings[path]):
                del self.mappings[path][idx]
        self._refresh_mappings_list()
        if self.preview_mode:
            self._schedule_live_preview()

    def clear_mappings(self):
        if self.batch_mode.get() == 'all_same':
            if messagebox.askyesno("Onay", "Tum ortak eslesmeleri silmek istediginize emin misiniz?"):
                self.shared_mappings.clear()
        else:
            if self.current_image_idx < 0:
                return
            path = self.image_list[self.current_image_idx]
            if messagebox.askyesno("Onay", f"{path.name} icin tum eslesmeleri silmek istediginize emin misiniz?"):
                self.mappings[path] = []
        self._refresh_mappings_list()
        if self.preview_mode:
            self.preview_mode = False
            self.preview_btn.config(text="Onizle")
            if self.current_image_idx >= 0:
                path = self.image_list[self.current_image_idx]
                self._display_image(self.original_images[path])

    def save_mappings(self):
        if self.batch_mode.get() == 'all_same':
            data_to_save = self.shared_mappings
        elif self.current_image_idx >= 0:
            path = self.image_list[self.current_image_idx]
            data_to_save = self.mappings.get(path, [])
        else:
            messagebox.showwarning("Uyari", "Kaydedilecek eslesme yok.")
            return

        if not data_to_save:
            messagebox.showwarning("Uyari", "Kaydedilecek eslesme yok.")
            return

        path = save_file(
            initial_dir=str(APP_DIR),
            default_name="mappings.json",
            file_types=[("JSON", "*.json")],
            title="Eslesmeleri kaydet")
        if not path:
            return
        data = {"points": [{"src": list(m["src"]), "dst": list(m["dst"])}
                          for m in data_to_save]}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.status_var.set(f"Eslesmeler kaydedildi: {path}")

    def load_mappings(self):
        path = open_file(
            initial_dir=str(APP_DIR),
            file_types=[("JSON", "*.json")],
            title="Eslesme dosyasi sec")
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            points = data.get('points', data) if isinstance(data, dict) else data
            loaded = [{"src": tuple(p["src"]), "dst": tuple(p["dst"])}
                    for p in points]
            if self.batch_mode.get() == 'all_same':
                self.shared_mappings = loaded
            else:
                if self.current_image_idx < 0:
                    messagebox.showwarning("Uyari",
                        "Once bir resim acin veya 'Tum resimlere ayni' moduna gecin.")
                    return
                target = self.image_list[self.current_image_idx]
                self.mappings[target] = loaded
            self._refresh_mappings_list()
            self.status_var.set(f"Eslesmeler yuklendi: {len(loaded)} nokta.")
        except Exception as e:
            messagebox.showerror("Hata", f"Yuklenemedi:\n{e}")

    # ============================================================
    # DONUSUM
    # ============================================================

    def _build_warp_for(self, path):
        """Main thread'de: bu resim icin ColorWarp kur."""
        mappings = self._get_mappings_for(path)
        if not mappings:
            return None
        try:
            return self._build_warp_from_lists(
                [m["src"] for m in mappings],
                [m["dst"] for m in mappings],
                self._snapshot_params())
        except Exception as e:
            print(f"Warp hatasi: {e}")
            return None

    def _build_warp_from_lists(self, src_colors, tgt_colors, params):
        """Saf kurucu: Tk'ye dokunmaz; thread icinde de kullanilabilir."""
        return ColorWarp(
            source_colors=src_colors,
            target_colors=tgt_colors,
            softness=params['softness'],
            snap=params['snap'])

    def save_result(self):
        if self.current_image_idx < 0:
            messagebox.showwarning("Uyari", "Once bir resim acin.")
            return
        path = self.image_list[self.current_image_idx]
        warp = self._build_warp_for(path)
        if warp is None:
            messagebox.showwarning("Uyari", "Hic eslesme yok.")
            return
        out_path = save_file(
            initial_dir=str(OUTPUT_DIR),
            default_name=f"recolor_{path.stem}.png",
            file_types=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("TIFF", "*.tiff")],
            title="Sonucu kaydet")
        if not out_path:
            return
        # Tam cozunurluk hesabi arka planda (arayuz donmaz);
        # parametreler main thread'de okunup duz veri olarak gecilir.
        params = self._snapshot_params()
        arr = self.image_arrays[path]

        def worker():
            try:
                result = warp.apply(arr, strength=params['strength'])
                Image.fromarray(result).save(out_path)
                self.root.after(0, lambda: self._save_result_done(out_path))
            except Exception as e:
                print(f"Kaydetme hatasi: {e}")
                self.root.after(0, lambda: messagebox.showerror(
                    "Hata", f"Kaydedilemedi:\n{e}"))
                self.root.after(0, lambda: self.status_var.set("Kaydetme hatasi."))

        self.status_var.set("Hesaplaniyor (tam cozunurluk, arka planda)...")
        threading.Thread(target=worker, daemon=True).start()

    def _save_result_done(self, out_path):
        self.status_var.set(f"Kaydedildi: {out_path}")
        messagebox.showinfo("Tamam", f"Sonuc kaydedildi:\n{out_path}")

    # ============================================================
    # TOPLU ISLE
    # ============================================================

    def process_all(self):
        if not self.image_list:
            messagebox.showwarning("Uyari", "Hic dosya yuklu degil.")
            return

        # Hangi resimlerin islem gorucegi?
        if self.batch_mode.get() == 'all_same':
            if not self.shared_mappings:
                messagebox.showwarning("Uyari",
                    "Ortak eslesmeler bos. Once eslestirme yapin.")
                return
            targets = self.image_list
        else:
            # Sadece mappings'i olan resimleri isle
            targets = [p for p in self.image_list if self.mappings.get(p)]
            if not targets:
                messagebox.showwarning("Uyari",
                    "Hicbir resim icin eslesme yok. Once eslestirme yapin.")
                return

        # Onay
        msg = f"{len(targets)} resim islenecek. output/ klasorune kaydedilecek.\n\nDevam?"
        if not messagebox.askyesno("Onay", msg):
            return

        # Warp'ler MAIN thread'de kurulur (Tk degiskenlerine arka plandan
        # dokunulmaz); thread'e duz veri gecilir.
        params = self._snapshot_params()
        warps = {}
        for p in targets:
            mappings = self._get_mappings_for(p)
            if not mappings:
                continue
            try:
                warps[p] = self._build_warp_from_lists(
                    [m["src"] for m in mappings],
                    [m["dst"] for m in mappings], params)
            except Exception as e:
                print(f"Warp hatasi {p}: {e}")

        if not warps:
            messagebox.showwarning("Uyari", "Eslesmeler olusturulamadi.")
            return

        # Ayri thread'de calistir
        self.status_var.set(f"Toplu islem basladi: {len(warps)} resim...")
        t = threading.Thread(target=self._process_all_thread,
                            args=(warps, params['strength']), daemon=True)
        t.start()

    def _process_all_thread(self, warps, strength):
        ok_count = 0
        fail_count = 0
        total = len(warps)
        for i, (path, warp) in enumerate(warps.items()):
            try:
                arr = self.image_arrays[path]
                result = warp.apply(arr, strength=strength)
                out_path = self._unique_output_path(path)
                Image.fromarray(result).save(out_path)
                ok_count += 1
                # Status guncelle
                self.root.after(0, lambda i=i, n=total, p=path:
                    self.status_var.set(
                        f"Isleniyor {i+1}/{n}: {p.name}"))
            except Exception as e:
                print(f"Hata {path}: {e}")
                fail_count += 1

        self.root.after(0, lambda: self._process_all_done(ok_count, fail_count))

    def _unique_output_path(self, path):
        """recolor_<isim>.png; ayni dosya varsa _2, _3... ekler (ezmez)."""
        base = OUTPUT_DIR / f"recolor_{path.stem}.png"
        if not base.exists():
            return base
        n = 2
        while True:
            candidate = OUTPUT_DIR / f"recolor_{path.stem}_{n}.png"
            if not candidate.exists():
                return candidate
            n += 1

    def _process_all_done(self, ok, fail):
        self.status_var.set(f"Tamamlandi: {ok} basarili, {fail} basarisiz. "
                            f"Cikti: {OUTPUT_DIR}")
        messagebox.showinfo("Tamamlandi",
            f"Islem tamamlandi.\n\nBasarili: {ok}\nBasarisiz: {fail}\n\n"
            f"Cikti klasoru: {OUTPUT_DIR}")


    # ============================================================
    # CIKIS
    # ============================================================

    def on_close(self):
        """Program kapanirken input/'daki YALNIZ bu oturumun kopyalarini siler.

        Kullanicinin kendi dosyalarina ve onceki oturumlardan kalan
        dosyalara dokunulmaz."""
        cleaned = 0
        for f in self.session_files:
            try:
                if f.exists() and f.parent == INPUT_DIR:
                    f.unlink()
                    cleaned += 1
            except Exception:
                pass
        if cleaned:
            print(f"input/ temizligi: {cleaned} oturum kopyasi silindi.")
        self.root.destroy()


# ============================================================
# GIRIS
# ============================================================

def main():
    root = tk.Tk()
    app = RecolorGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
