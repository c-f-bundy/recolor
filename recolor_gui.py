#!/usr/bin/env python3
"""
Recolor GUI v0.3.0 - Renk Standardizasyon Araci

v0.3.0 degisiklikleri:
- Daha buyuk font ve butonlar
- Native dosya gezgini (zenity)
- output/, palettes/, input/ klasorleri (uygulama dizininde)
- Toplu dosya/klasor yukleme
- Thumbnail grid view (tek tik=cerceve, cift tik=ac)
- Klavye navigasyonu (Sol/Sag ok) + ok butonlari
- Islem modu secimi (ayri ayri / hepsine ayni)
- Ctrl+tekerlek=dikey, Shift+tekerlek=yatay scroll
- LAB->RGB uyarilari bastirildi
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
FONT_SMALL = (FONT_FAMILY, 12)
FONT_NORMAL = (FONT_FAMILY, 13)
FONT_LARGE = (FONT_FAMILY, 15)
FONT_TITLE = (FONT_FAMILY, 16, 'bold')
FONT_BUTTON = (FONT_FAMILY, 13)
FONT_BUTTON_LARGE = (FONT_FAMILY, 14, 'bold')


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
        self.root.title("Recolor v0.3.0 - Renk Standardizasyon Araci")
        self.root.geometry("1500x950")
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
        self.preview_mode = False
        self.preview_lock = threading.Lock()
        self.preview_job = None

        self.zoom_factor = 1.0
        self.base_scale = 1.0

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
        file_menu.add_command(label="Cikis", command=self.root.quit)
        menubar.add_cascade(label="Dosya", menu=file_menu)

        # Ana yerlesim
        main_paned = tk.PanedWindow(self.root, orient=tk.HORIZONTAL,
                                   bg=Theme.BG, sashwidth=4,
                                   sashrelief=tk.FLAT)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # ---------------- SOL: GORUNTU ALANI ----------------
        image_frame = tk.Frame(main_paned, bg=Theme.BG)
        main_paned.add(image_frame, minsize=600, width=1000)

        # Ust kontrol cubugu
        ctrl = tk.Frame(image_frame, bg=Theme.BG_PANEL, height=60)
        ctrl.pack(fill=tk.X)
        tk.Button(ctrl, text="Dosya Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=16, pady=10,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_files).pack(side=tk.LEFT, padx=4, pady=8)
        tk.Button(ctrl, text="Klasor Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=16, pady=10,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_directory).pack(side=tk.LEFT, padx=4, pady=8)
        tk.Button(ctrl, text="Onizle", bg=Theme.ACCENT, fg=Theme.BG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=16, pady=10,
                 activebackground=Theme.ACCENT_DARK, activeforeground=Theme.BG,
                 command=self.toggle_preview).pack(side=tk.LEFT, padx=4, pady=8)
        tk.Button(ctrl, text="Orijinali Goster", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=16, pady=10,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.show_original).pack(side=tk.LEFT, padx=4, pady=8)
        tk.Button(ctrl, text="Sonucu Kaydet", bg=Theme.SUCCESS, fg=Theme.BG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=16, pady=10,
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
        tk.Label(nav, text="(Sol/Sag ok: onceki/sonraki | Ctrl+tekerlek: dikey | "
                          "Shift+tekerlek: yatay | tekerlek: zoom)",
                bg=Theme.BG_PANEL, fg=Theme.FG_MUTED, font=FONT_SMALL).pack(
                    side=tk.RIGHT, padx=10)

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
        self.canvas.bind('<Button-4>', lambda e: self._zoom_at(e.x, e.y, 1.25))
        self.canvas.bind('<Button-5>', lambda e: self._zoom_at(e.x, e.y, 0.8))
        self.canvas.bind('<Control-MouseWheel>', self.on_ctrl_wheel)
        self.canvas.bind('<Shift-MouseWheel>', self.on_shift_wheel)
        # Linux icin Ctrl+tekerlek
        self.canvas.bind('<Control-Button-4>', lambda e: self._scroll_v(-1))
        self.canvas.bind('<Control-Button-5>', lambda e: self._scroll_v(1))
        self.canvas.bind('<Shift-Button-4>', lambda e: self._scroll_h(-1))
        self.canvas.bind('<Shift-Button-5>', lambda e: self._scroll_h(1))

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

        # ---------------- SAG: KONTROL ----------------
        control_frame = tk.Frame(main_paned, bg=Theme.BG, width=480)
        main_paned.add(control_frame, minsize=420)

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

        # ----- UST: KAYNAK + ESLESMELER -----
        top_frame = tk.Frame(paned, bg=Theme.BG_PANEL)
        paned.add(top_frame, minsize=250, height=450)

        # Kaynak renk
        src_frame = tk.LabelFrame(top_frame, text=" Kaynak Renk ",
                                 bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                 font=FONT_LARGE, bd=2,
                                 highlightbackground=Theme.BORDER,
                                 highlightthickness=1, padx=10, pady=10)
        src_frame.pack(fill=tk.X, padx=4, pady=4)

        src_top = tk.Frame(src_frame, bg=Theme.BG_PANEL)
        src_top.pack(fill=tk.X)

        self.source_swatch = tk.Label(src_top, bg='#808080', width=6, height=3,
                                     relief=tk.SOLID, bd=1,
                                     highlightbackground=Theme.SWATCH_BORDER,
                                     highlightthickness=1)
        self.source_swatch.pack(side=tk.LEFT, padx=(0, 10))

        self.source_rgb_var = tk.StringVar(
            value="Henutz secilmedi\n(gorsele tikla veya asagidan ayarla)")
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
                 command=self._use_rgb_as_source).pack(pady=(10, 0),
                                                                       fill=tk.X)

        # Eslesmeler listesi
        list_frame = tk.LabelFrame(top_frame, text=" Eslesmeler ",
                                  bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                  font=FONT_LARGE, bd=2,
                                  highlightbackground=Theme.BORDER,
                                  highlightthickness=1, padx=10, pady=10)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        list_canvas_frame = tk.Frame(list_frame, bg=Theme.BG_PANEL)
        list_canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.list_canvas = tk.Canvas(list_canvas_frame, bg=Theme.BG_PANEL,
                                    highlightthickness=0, height=150)
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
                 font=FONT_BUTTON, relief=tk.FLAT, padx=10, pady=6,
                 activebackground='#c46a82', activeforeground=Theme.BG,
                 command=self.clear_mappings).pack(side=tk.LEFT, padx=2)
        tk.Button(list_btn, text="Kaydet", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=10, pady=6,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.save_mappings).pack(side=tk.RIGHT, padx=2)
        tk.Button(list_btn, text="Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=10, pady=6,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_mappings).pack(side=tk.RIGHT, padx=2)

        # ----- ALT: PALET -----
        bot_frame = tk.Frame(paned, bg=Theme.BG_PANEL)
        paned.add(bot_frame, minsize=200, height=350)

        pal_frame = tk.LabelFrame(bot_frame, text=" Palet (hedef icin tikla) ",
                                 bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                 font=FONT_LARGE, bd=2,
                                 highlightbackground=Theme.BORDER,
                                 highlightthickness=1, padx=10, pady=10)
        pal_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        pal_ctrl = tk.Frame(pal_frame, bg=Theme.BG_PANEL)
        pal_ctrl.pack(fill=tk.X, pady=(0, 8))
        tk.Button(pal_ctrl, text=".gpl Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=10, pady=6,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_palette_gpl).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text=".gpl Kaydet", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=10, pady=6,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.save_palette_gpl).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text="RGB Ekle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=10, pady=6,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.add_color_manual).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text="Temizle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_BUTTON, relief=tk.FLAT, padx=10, pady=6,
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
        self.palette_canvas.bind("<Configure>",
            lambda e: self.palette_canvas.itemconfig(
                self.palette_window_id, width=e.width))
        self.palette_canvas.configure(yscrollcommand=pal_scroll.set)
        self.palette_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pal_scroll.pack(side=tk.RIGHT, fill=tk.Y)

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
                                   highlightthickness=1, padx=12, pady=12)
        batch_frame.pack(fill=tk.X, pady=8)

        tk.Radiobutton(batch_frame, text="  Her resim icin ayri eslestirme (default)",
                      variable=self.batch_mode, value='per_image',
                      bg=Theme.BG_PANEL, fg=Theme.FG, selectcolor=Theme.BG_INPUT,
                      activebackground=Theme.BG_PANEL, activeforeground=Theme.FG,
                      font=FONT_NORMAL, highlightthickness=0, bd=0,
                      command=self.on_batch_mode_change).pack(anchor=tk.W, pady=3)
        tk.Radiobutton(batch_frame, text="  Tum resimlere ayni eslestirme uygula",
                      variable=self.batch_mode, value='all_same',
                      bg=Theme.BG_PANEL, fg=Theme.FG, selectcolor=Theme.BG_INPUT,
                      activebackground=Theme.BG_PANEL, activeforeground=Theme.FG,
                      font=FONT_NORMAL, highlightthickness=0, bd=0,
                      command=self.on_batch_mode_change).pack(anchor=tk.W, pady=3)
        tk.Label(batch_frame,
                text="Ayri: her resim kendi eslesmelerini kullanir.\n"
                     "Ayni: tek bir eslestirme listesi tum resimlere uygulanir.",
                bg=Theme.BG_PANEL, fg=Theme.FG_MUTED, font=FONT_SMALL,
                justify=tk.LEFT).pack(anchor=tk.W, pady=(6, 0))

        # Mod secimi
        self.mode_frame = tk.LabelFrame(container, text=" Donusum Modu ",
                                       bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                       font=FONT_LARGE, bd=2,
                                       highlightbackground=Theme.BORDER,
                                       highlightthickness=1, padx=12, pady=12)
        self.mode_frame.pack(fill=tk.X, pady=8)
        self._mode_frame_ref = self.mode_frame

        self.mode_var = tk.StringVar(value='single')
        tk.Radiobutton(self.mode_frame, text="  Tek Kaydirici (Tension)",
                      variable=self.mode_var, value='single',
                      bg=Theme.BG_PANEL, fg=Theme.FG, selectcolor=Theme.BG_INPUT,
                      activebackground=Theme.BG_PANEL, activeforeground=Theme.FG,
                      font=FONT_NORMAL, command=self.on_mode_change,
                      highlightthickness=0, bd=0).pack(anchor=tk.W, pady=2)
        tk.Radiobutton(self.mode_frame, text="  Cift Kaydirici (Softness + Snap)",
                      variable=self.mode_var, value='dual',
                      bg=Theme.BG_PANEL, fg=Theme.FG, selectcolor=Theme.BG_INPUT,
                      activebackground=Theme.BG_PANEL, activeforeground=Theme.FG,
                      font=FONT_NORMAL, command=self.on_mode_change,
                      highlightthickness=0, bd=0).pack(anchor=tk.W, pady=2)

        self.single_frame = tk.LabelFrame(container, text=" Tek Kaydirici ",
                                         bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                         font=FONT_LARGE, bd=2,
                                         highlightbackground=Theme.BORDER,
                                         highlightthickness=1, padx=12, pady=12)
        self._add_slider(self.single_frame, "Tension (Gerginlik)",
                        'tension', 0.0, 1.0, 0.5,
                        "0 = yumusak gecisler, 1 = siki palet")

        self.dual_frame = tk.LabelFrame(container, text=" Cift Kaydirici ",
                                       bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                       font=FONT_LARGE, bd=2,
                                       highlightbackground=Theme.BORDER,
                                       highlightthickness=1, padx=12, pady=12)
        self._add_slider(self.dual_frame, "Softness (Etki Genisligi)",
                        'softness', 0.0, 1.0, 0.5,
                        "0 = dar etki, 1 = genis etki")
        self._add_slider(self.dual_frame, "Snap (Palet Yapismasi)",
                        'snap', 0.0, 1.0, 0.0,
                        "0 = yapismasiz, 1 = tam palet yapismasi")

        str_frame = tk.LabelFrame(container, text=" Etki Gucu ",
                                 bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                 font=FONT_LARGE, bd=2,
                                 highlightbackground=Theme.BORDER,
                                 highlightthickness=1, padx=12, pady=12)
        str_frame.pack(fill=tk.X, pady=8)
        self._add_slider(str_frame, "Strength (Opaklik)", 'strength',
                        0.0, 1.0, 1.0, "0 = orijinal, 1 = tam donusum")

        info_frame = tk.LabelFrame(container, text=" Bilgi ",
                                  bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                  font=FONT_LARGE, bd=2,
                                  highlightbackground=Theme.BORDER,
                                  highlightthickness=1, padx=12, pady=12)
        info_frame.pack(fill=tk.BOTH, expand=True, pady=8)
        tk.Label(info_frame,
                text="Klasor yapisi:\n"
                     f"  {APP_DIR}\n"
                     f"    input/     -> yuklenen dosyalarin kopyasi\n"
                     f"    output/    -> islenmis sonuclar\n"
                     f"    palettes/  -> palet dosyalari\n\n"
                     "Kisayollar:\n"
                     "  Sol/Sag ok    -> onceki/sonraki resim\n"
                     "  Ctrl+tekerlek -> dikey scroll\n"
                     "  Shift+tekerlek-> yatay scroll\n"
                     "  tekerlek      -> zoom\n"
                     "  cift tik      -> grid <-> tekil goruntu",
                bg=Theme.BG_PANEL, fg=Theme.FG, font=FONT_NORMAL,
                justify=tk.LEFT).pack(anchor=tk.W, padx=8, pady=8)

        self.on_mode_change()

    def _add_slider(self, parent, label, var_name, vmin, vmax, default, hint):
        tk.Label(parent, text=label, bg=Theme.BG_PANEL, fg=Theme.FG,
                font=FONT_NORMAL, anchor=tk.W).pack(fill=tk.X, pady=(8, 0))

        row = tk.Frame(parent, bg=Theme.BG_PANEL)
        row.pack(fill=tk.X, pady=2)

        var = tk.DoubleVar(value=default)
        setattr(self, f"{var_name}_var", var)

        val_label = tk.Label(row, text=f"{default:.2f}", width=8,
                            bg=Theme.BG_PANEL, fg=Theme.ACCENT, font=FONT_NORMAL,
                            anchor=tk.E)
        val_label.pack(side=tk.LEFT, padx=(0, 8))
        setattr(self, f"{var_name}_value_label", val_label)

        scale = tk.Scale(row, from_=vmin, to=vmax, orient=tk.HORIZONTAL,
                        variable=var, showvalue=False,
                        bg=Theme.BG_PANEL, fg=Theme.FG,
                        troughcolor=Theme.BG_INPUT, highlightthickness=0,
                        sliderrelief=tk.FLAT, activebackground=Theme.ACCENT_DARK,
                        length=240, resolution=0.01, font=FONT_SMALL,
                        command=lambda v, n=var_name: self._on_slider_change(n))
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        tk.Label(parent, text=hint, bg=Theme.BG_PANEL, fg=Theme.FG_MUTED,
                font=FONT_SMALL, anchor=tk.W).pack(fill=tk.X, pady=(0, 8))

    def _on_slider_change(self, name):
        var = getattr(self, f"{name}_var")
        label = getattr(self, f"{name}_value_label")
        label.config(text=f"{var.get():.2f}")
        if self.preview_mode:
            self._schedule_live_preview()

    def _schedule_live_preview(self):
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(200, self._do_live_preview)

    def _do_live_preview(self):
        if not self.preview_mode:
            return
        if self.current_image_idx < 0:
            return
        path = self.image_list[self.current_image_idx]
        if path not in self.image_arrays:
            return
        mappings = self._get_mappings_for(path)
        if not mappings:
            return
        t = threading.Thread(target=self._live_preview_thread,
                            args=(path,), daemon=True)
        t.start()

    def _live_preview_thread(self, path):
        with self.preview_lock:
            try:
                warp = self._build_warp_for(path)
                if warp is None:
                    return
                preview_arr = self._compute_preview(warp, path)
                if preview_arr is None:
                    return
                self.preview_array = preview_arr
                self.root.after(0, lambda: self._display_array(preview_arr))
            except Exception as e:
                print(f"Live preview hatasi: {e}")

    def _compute_preview(self, warp, path):
        arr = self.image_arrays.get(path)
        if arr is None:
            return None
        H, W = arr.shape[:2]
        max_dim = 800
        if max(H, W) > max_dim:
            scale = max_dim / max(H, W)
            small = Image.fromarray(arr).resize(
                (int(W*scale), int(H*scale)), Image.LANCZOS)
            small_arr = np.array(small)
            return warp.apply(small_arr, strength=self.strength_var.get())
        return warp.apply(arr, strength=self.strength_var.get())

    def on_mode_change(self):
        if self.mode_var.get() == 'single':
            self.dual_frame.pack_forget()
            self.single_frame.pack(fill=tk.X, pady=8, after=self._mode_frame_ref)
        else:
            self.single_frame.pack_forget()
            self.dual_frame.pack(fill=tk.X, pady=8, after=self._mode_frame_ref)
        if self.preview_mode:
            self._schedule_live_preview()

    def on_batch_mode_change(self):
        # Modu degistirince UI'i guncelle
        if self.batch_mode.get() == 'all_same':
            self._refresh_mappings_list()
        else:
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
        """Dosyalari yukle, input/ klasorune kopyala, grid view'a ekle."""
        new_count = 0
        for fp in file_paths:
            src = Path(fp)
            # input/'a kopyala
            try:
                dest = INPUT_DIR / src.name
                if not dest.exists():
                    shutil.copy2(src, dest)
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

    def _create_thumbnail(self, path, pil_image):
        """Verilen path icin thumbnail olustur ve kaydet."""
        thumb = pil_image.copy()
        thumb.thumbnail((180, 180), Image.LANCZOS)
        self.thumbnails[path] = ImageTk.PhotoImage(thumb)

    # ============================================================
    # GRID VIEW
    # ============================================================

    def show_grid(self):
        """Yuklenen tum resimleri grid view olarak goster."""
        self.preview_mode = False
        self.current_image_idx = -1
        self.canvas.delete("all")
        self.thumbnail_labels.clear()

        if not self.image_list:
            self.status_var.set("Hic dosya yuklu degil.")
            return

        # Grid yerlesimi: 5 sutun
        cols = 5
        thumb_size = 180
        padding = 10
        cell_w = thumb_size + padding * 2

        for i, path in enumerate(self.image_list):
            r, c = divmod(i, cols)
            x = c * cell_w + padding
            y = r * cell_w + padding

            # Thumbnail cercevesi (arka plan)
            bg_color = Theme.ACCENT_SELECTED if path == self.selected_thumb else Theme.BG_LIST_ITEM
            bg_rect = self.canvas.create_rectangle(
                x - 2, y - 2, x + thumb_size + 2, y + thumb_size + 2,
                fill=bg_color, outline='', tags=f'thumb_{i}')

            # Thumbnail
            photo = self.thumbnails.get(path)
            if photo:
                img_item = self.canvas.create_image(
                    x + thumb_size // 2, y + thumb_size // 2,
                    image=photo, tags=f'img_{i}')

            # Dosya adi (altinda)
            name = path.name
            if len(name) > 24:
                name = name[:21] + '...'
            self.canvas.create_text(
                x + thumb_size // 2, y + thumb_size + 8,
                text=name, fill=Theme.FG_MUTED, font=FONT_SMALL,
                tags=f'name_{i}')

            # Baglama: tek tik = secili, cift tik = ac
            self.canvas.tag_bind(f'img_{i}', '<Button-1>',
                lambda e, p=path: self._on_thumb_click(p))
            self.canvas.tag_bind(f'img_{i}', '<Double-Button-1>',
                lambda e, p=path: self._on_thumb_double_click(p))
            self.canvas.tag_bind(f'thumb_{i}', '<Button-1>',
                lambda e, p=path: self._on_thumb_click(p))
            self.canvas.tag_bind(f'thumb_{i}', '<Double-Button-1>',
                lambda e, p=path: self._on_thumb_double_click(p))

        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        self.zoom_factor = 1.0
        self._update_zoom_label()
        self.nav_info.set(f"0 / {len(self.image_list)} (grid view)")

    def _on_thumb_click(self, path):
        """Tek tik: sadece cerceve rengini degistir."""
        self.selected_thumb = path
        # Grid'i yeniden ciz (cerceve renklerini guncellemek icin)
        self.show_grid()

    def _on_thumb_double_click(self, path):
        """Cift tik: resmi ac."""
        idx = self.image_list.index(path)
        self._open_image_at(idx)

    def _open_image_at(self, idx):
        """Verilen indeksteki resmi tam ekran ac."""
        if idx < 0 or idx >= len(self.image_list):
            return
        self.current_image_idx = idx
        path = self.image_list[idx]
        self.zoom_factor = 1.0
        self.preview_mode = False
        self.preview_array = None
        self._display_image(self.original_images[path])
        self.nav_info.set(f"{idx+1} / {len(self.image_list)}")
        self.status_var.set(f"Acik: {path.name}")
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
        canvas_w = max(self.canvas.winfo_width(), 600)
        canvas_h = max(self.canvas.winfo_height(), 400)
        w, h = pil_image.size
        base = min(canvas_w / w, canvas_h / h, 1.0)
        self.base_scale = base
        total = base * self.zoom_factor
        new_w, new_h = max(int(w * total), 1), max(int(h * total), 1)
        resized = pil_image.resize((new_w, new_h), Image.LANCZOS)
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

    def show_original(self):
        if self.current_image_idx < 0:
            messagebox.showwarning("Uyari", "Once bir resim acin (cift tikla).")
            return
        path = self.image_list[self.current_image_idx]
        self.preview_mode = False
        self._display_image(self.original_images[path])
        self.status_var.set("Orijinal gosteriliyor.")

    def toggle_preview(self):
        if self.current_image_idx < 0:
            messagebox.showwarning("Uyari", "Once bir resim acin.")
            return
        path = self.image_list[self.current_image_idx]
        mappings = self._get_mappings_for(path)
        if not mappings:
            messagebox.showwarning("Uyari", "Hic eslesme yok.")
            return
        if self.preview_mode:
            self.preview_mode = False
            self._display_image(self.original_images[path])
            self.status_var.set("Canli onizleme kapandi.")
        else:
            self.preview_mode = True
            self.status_var.set("Canli onizleme acik.")
            self._schedule_live_preview()

    # ============================================================
    # ZOOM / SCROLL
    # ============================================================

    def on_mouse_wheel(self, event):
        if event.delta > 0:
            factor = 1.15
        else:
            factor = 0.87
        self._zoom_at(event.x, event.y, factor)

    def on_ctrl_wheel(self, event):
        """Ctrl + tekerlek = dikey scroll (Linux'ta Button-4/5 kullanilir)."""
        if event.delta > 0:
            self._scroll_v(-2)
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
        if self.current_image_idx < 0:
            return
        old_zoom = self.zoom_factor
        new_zoom = max(0.1, min(10.0, old_zoom * factor))
        if new_zoom == old_zoom:
            return
        self.zoom_factor = new_zoom
        if self.preview_mode and self.preview_array is not None:
            self._display_array(self.preview_array)
        else:
            path = self.image_list[self.current_image_idx]
            self._display_image(self.original_images[path])

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

    def _render_palette(self):
        for sw in self.palette_swatches:
            sw.destroy()
        self.palette_swatches.clear()
        cols = 5
        for i, color in enumerate(self.palette):
            r, c = divmod(i, cols)
            hex_c = '#%02x%02x%02x' % color
            sw = tk.Label(self.palette_inner, bg=hex_c, width=8, height=4,
                         relief=tk.FLAT, bd=0,
                         highlightbackground=Theme.SWATCH_BORDER,
                         highlightthickness=1, cursor='hand2')
            sw.grid(row=r, column=c, padx=3, pady=3, sticky='nsew')
            sw.bind('<Button-1>', lambda e, c=color: self.on_palette_click(c))
            sw.bind('<Button-3>', lambda e, c=color: self._show_color_info(c))
            sw.bind('<Enter>', lambda e, w=sw: w.config(
                highlightbackground=Theme.ACCENT, highlightthickness=2))
            sw.bind('<Leave>', lambda e, w=sw: w.config(
                highlightbackground=Theme.SWATCH_BORDER, highlightthickness=1))
            self.palette_swatches.append(sw)
        for c in range(cols):
            self.palette_inner.columnconfigure(c, weight=1)
        self.palette_info_var.set(f"{len(self.palette)} renk")

    def on_palette_click(self, color):
        if self.picked_source is None:
            messagebox.showinfo("Bilgi",
                "Once kaynak renk secin (gorsele tikla veya RGB ayarla).")
            return
        if self.current_image_idx < 0 and self.batch_mode.get() == 'per_image':
            messagebox.showinfo("Bilgi",
                "Once bir resim acin (cift tik) veya 'Tum resimlere ayni' moduna gecin.")
            return

        # Mapping ekle
        if self.batch_mode.get() == 'all_same':
            self.shared_mappings.append({"src": self.picked_source, "dst": color})
        else:
            path = self.image_list[self.current_image_idx]
            if path not in self.mappings:
                self.mappings[path] = []
            self.mappings[path].append({"src": self.picked_source, "dst": color})

        self._refresh_mappings_list()

        if self.preview_mode:
            self.preview_mode = False
            if self.current_image_idx >= 0:
                path = self.image_list[self.current_image_idx]
                self._display_image(self.original_images[path])
            self.status_var.set("Eslesme eklendi. Canli mod kapandi.")
        else:
            self.status_var.set(f"Eslesme eklendi.")

        # Kaynak secimi temizle
        self.picked_source = None
        self.source_swatch.config(bg='#808080')
        self.source_rgb_var.set("Henutz secilmedi\n(gorsele tikla veya asagidan ayarla)")

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
            return

        for i, m in enumerate(current):
            row = self._build_mapping_row(self.list_inner, i, m)
            row.pack(fill=tk.X, padx=2, pady=2)

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
        mappings = self._get_mappings_for(path)
        if not mappings:
            return None
        src = [m["src"] for m in mappings]
        tgt = [m["dst"] for m in mappings]
        try:
            return ColorWarp(
                source_colors=src, target_colors=tgt,
                mode=self.mode_var.get(),
                tension=self.tension_var.get(),
                softness=self.softness_var.get(),
                snap=self.snap_var.get())
        except Exception as e:
            print(f"Warp hatasi: {e}")
            return None

    def _build_warp_internal(self):
        if self.current_image_idx < 0:
            return None
        return self._build_warp_for(self.image_list[self.current_image_idx])

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
        try:
            self.status_var.set("Hesaplaniyor (tam cozunurluk)...")
            self.root.update()
            result = warp.apply(self.image_arrays[path],
                              strength=self.strength_var.get())
            Image.fromarray(result).save(out_path)
            self.status_var.set(f"Kaydedildi: {out_path}")
            messagebox.showinfo("Tamam", f"Sonuc kaydedildi:\n{out_path}")
        except Exception as e:
            messagebox.showerror("Hata", f"Kaydedilemedi:\n{e}")

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

        # Ayri thread'de calistir
        self.status_var.set(f"Toplu islem basladi: {len(targets)} resim...")
        t = threading.Thread(target=self._process_all_thread,
                            args=(targets,), daemon=True)
        t.start()

    def _process_all_thread(self, targets):
        ok_count = 0
        fail_count = 0
        for i, path in enumerate(targets):
            try:
                warp = self._build_warp_for(path)
                if warp is None:
                    fail_count += 1
                    continue
                arr = self.image_arrays[path]
                result = warp.apply(arr, strength=self.strength_var.get())
                out_path = OUTPUT_DIR / f"recolor_{path.stem}.png"
                Image.fromarray(result).save(out_path)
                ok_count += 1
                # Status guncelle
                self.root.after(0, lambda i=i, n=len(targets), p=path:
                    self.status_var.set(
                        f"Isleniyor {i+1}/{n}: {p.name}"))
            except Exception as e:
                print(f"Hata {path}: {e}")
                fail_count += 1

        self.root.after(0, lambda: self._process_all_done(ok_count, fail_count))

    def _process_all_done(self, ok, fail):
        self.status_var.set(f"Tamamlandi: {ok} basarili, {fail} basarisiz. "
                            f"Cikti: {OUTPUT_DIR}")
        messagebox.showinfo("Tamamlandi",
            f"Islem tamamlandi.\n\nBasarili: {ok}\nBasarisiz: {fail}\n\n"
            f"Cikti klasoru: {OUTPUT_DIR}")


# ============================================================
# GIRIS
# ============================================================

def main():
    root = tk.Tk()
    app = RecolorGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
