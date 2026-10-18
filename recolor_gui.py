#!/usr/bin/env python3
"""
Recolor GUI v2 - Renk Standardizasyon Araci

Yeni:
- Koyu tema, buyuk yazi/butonlar
- Slider duzeltmesi (tkr tklamada savrulma yok)
- Slider altinda deger gosterimi
- Fare tekerlegi ile zoom
- Eslesmeler ve palet ayni sekmede
- Kaynak ve hedef renkler icin gorsel kutucuk + ok
- RGB slider'lari (kaynak renk elle girilebilir)
- Canli onizleme (slider degistiginde otomatik)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import sys
import threading
from pathlib import Path
from PIL import Image, ImageTk
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from recolor_core import ColorWarp


# ============================================================
# TEMA
# ============================================================

class Theme:
    BG = '#1e1e2e'           # ana arka plan
    BG_PANEL = '#2a2a3c'     # panel arka plani
    BG_INPUT = '#3a3a4e'     # input arka plani
    BG_HOVER = '#4a4a5e'     # hover
    FG = '#e0e0e8'           # ana yazi
    FG_MUTED = '#9090a0'     # ikincil yazi
    ACCENT = '#89b4fa'       # vurgu mavisi
    ACCENT_DARK = '#5a7fb8'  # koyu vurgu
    DANGER = '#f38ba8'       # kirmizi
    SUCCESS = '#a6e3a1'      # yesil
    BORDER = '#4a4a5e'       # kenarlik
    SWATCH_BORDER = '#6a6a8e'


# ============================================================
# FONTLAR
# ============================================================

FONT_FAMILY = 'DejaVu Sans'  # Linux'ta standart
FONT_NORMAL = (FONT_FAMILY, 11)
FONT_SMALL = (FONT_FAMILY, 10)
FONT_LARGE = (FONT_FAMILY, 13)
FONT_TITLE = (FONT_FAMILY, 14, 'bold')


# ============================================================
# ANA PENCERE
# ============================================================

class RecolorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Recolor - Renk Standardizasyon Araci")
        self.root.geometry("1400x900")
        self.root.minsize(1000, 700)
        self.root.configure(bg=Theme.BG)

        # --- Durum ---
        self.original_image = None        # PIL Image (orijinal)
        self.image_array = None           # numpy (H, W, 3) uint8
        self.display_photo = None         # ImageTk.PhotoImage
        self.zoom_factor = 1.0            # kullanici zoom faktoru
        self.base_scale = 1.0             # ekrana sigdirma olcegi
        self.palette = []
        self.palette_swatches = []
        self.mappings = []                # [{"src":(r,g,b), "dst":(r,g,b)}, ...]
        self.picked_source = None         # (r,g,b) veya None
        self.preview_array = None
        self.preview_mode = False         # canli onizleme aktif mi
        self.hover_label = None
        self.mapping_widgets = []         # eslesme satiri widget'lari
        self.preview_lock = threading.Lock()
        self.preview_job = None           # debounce icin after id
        self.current_warp = None          # son insa edilen ColorWarp
        self.last_settings_hash = None    # ayarlar degisti mi takip icin

        self._setup_theme()
        self._build_ui()
        self._setup_default_palette()

    # ============================================================
    # TEMA
    # ============================================================

    def _setup_theme(self):
        style = ttk.Style()
        try:
            style.theme_use('clam')
        except tk.TclError:
            pass

        # Genel stiller
        style.configure('.', background=Theme.BG, foreground=Theme.FG,
                       font=FONT_NORMAL, borderwidth=0)
        style.configure('TFrame', background=Theme.BG)
        style.configure('Panel.TFrame', background=Theme.BG_PANEL)
        style.configure('TLabel', background=Theme.BG, foreground=Theme.FG,
                       font=FONT_NORMAL)
        style.configure('Panel.TLabel', background=Theme.BG_PANEL,
                       foreground=Theme.FG, font=FONT_NORMAL)
        style.configure('Title.TLabel', background=Theme.BG_PANEL,
                       foreground=Theme.ACCENT, font=FONT_TITLE)
        style.configure('Muted.TLabel', background=Theme.BG_PANEL,
                       foreground=Theme.FG_MUTED, font=FONT_SMALL)
        style.configure('TLabelframe', background=Theme.BG_PANEL,
                       foreground=Theme.ACCENT, font=FONT_LARGE,
                       bordercolor=Theme.BORDER, relief='solid')
        style.configure('TLabelframe.Label', background=Theme.BG_PANEL,
                       foreground=Theme.ACCENT, font=FONT_LARGE)

        # Butonlar
        style.configure('TButton', background=Theme.BG_INPUT,
                       foreground=Theme.FG, font=FONT_NORMAL,
                       bordercolor=Theme.BORDER, focuscolor=Theme.ACCENT,
                       padding=(12, 6))
        style.map('TButton',
                 background=[('active', Theme.BG_HOVER),
                            ('pressed', Theme.ACCENT_DARK)],
                 foreground=[('pressed', Theme.BG)])

        style.configure('Accent.TButton', background=Theme.ACCENT,
                       foreground=Theme.BG, font=FONT_LARGE,
                       padding=(16, 8))
        style.map('Accent.TButton',
                 background=[('active', Theme.ACCENT_DARK),
                            ('pressed', Theme.ACCENT_DARK)])

        style.configure('Danger.TButton', background=Theme.DANGER,
                       foreground=Theme.BG, padding=(10, 4))
        style.map('Danger.TButton',
                 background=[('active', '#c46a82')])

        # Canvas
        style.configure('TCanvas', background='#15151f')

        # Treeview (eski eslesmeler listesi icin)
        style.configure('Treeview', background=Theme.BG_PANEL,
                       foreground=Theme.FG, fieldbackground=Theme.BG_PANEL,
                       bordercolor=Theme.BORDER, font=FONT_NORMAL)
        style.configure('Treeview.Heading', background=Theme.BG_INPUT,
                       foreground=Theme.ACCENT, font=FONT_NORMAL)

        # Scrollbar
        style.configure('TScrollbar', background=Theme.BG_PANEL,
                       troughcolor=Theme.BG, bordercolor=Theme.BORDER)

        # Notebook
        style.configure('TNotebook', background=Theme.BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=Theme.BG_PANEL,
                       foreground=Theme.FG_MUTED, padding=(16, 8),
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
                         activeforeground=Theme.FG, borderwidth=0)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0, bg=Theme.BG_PANEL,
                           fg=Theme.FG, activebackground=Theme.BG_HOVER,
                           activeforeground=Theme.FG)
        file_menu.add_command(label="Goruntu Yukle", command=self.load_image)
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
                                   sashpad=0, sashrelief=tk.FLAT)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # ---------------- SOL: GORUNTU ----------------
        image_frame = tk.Frame(main_paned, bg=Theme.BG)
        main_paned.add(image_frame, minsize=500, width=900)

        # Kontrol cubugu
        ctrl = tk.Frame(image_frame, bg=Theme.BG_PANEL, height=50)
        ctrl.pack(fill=tk.X, pady=0)
        tk.Button(ctrl, text="  Goruntu Yukle  ", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=12, pady=8,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_image).pack(side=tk.LEFT, padx=4, pady=6)
        tk.Button(ctrl, text="  Onizle  ", bg=Theme.ACCENT, fg=Theme.BG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=12, pady=8,
                 activebackground=Theme.ACCENT_DARK, activeforeground=Theme.BG,
                 command=self.toggle_preview).pack(side=tk.LEFT, padx=4, pady=6)
        tk.Button(ctrl, text="  Orijinali Goster  ", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=12, pady=8,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.show_original).pack(side=tk.LEFT, padx=4, pady=6)
        tk.Button(ctrl, text="  Sonucu Kaydet  ", bg=Theme.SUCCESS, fg=Theme.BG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=12, pady=8,
                 activebackground='#88c885', activeforeground=Theme.BG,
                 command=self.save_result).pack(side=tk.LEFT, padx=4, pady=6)

        # Zoom bilgisi
        self.zoom_var = tk.StringVar(value="Zoom: 100%")
        tk.Label(ctrl, textvariable=self.zoom_var, bg=Theme.BG_PANEL,
                fg=Theme.FG_MUTED, font=FONT_SMALL).pack(side=tk.RIGHT, padx=10)

        # Goruntu canvasi
        canvas_frame = tk.Frame(image_frame, bg='#15151f')
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg='#15151f', highlightthickness=0,
                               cursor='crosshair')
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

        # Mouse olaylari
        self.canvas.bind('<Button-1>', self.on_canvas_click)
        self.canvas.bind('<Motion>', self.on_canvas_motion)
        self.canvas.bind('<Leave>', lambda e: self.hover_label.config(
            text='--', bg=Theme.BG_PANEL, fg=Theme.FG_MUTED))
        self.canvas.bind('<MouseWheel>', self.on_mouse_wheel)        # Linux/Windows
        self.canvas.bind('<Button-4>', lambda e: self._zoom_at(e.x, e.y, 1.25))   # Linux yukari
        self.canvas.bind('<Button-5>', lambda e: self._zoom_at(e.x, e.y, 0.8))    # Linux asagi

        # Durum cubugu
        status = tk.Frame(image_frame, bg=Theme.BG_PANEL, height=30)
        status.pack(fill=tk.X)
        tk.Label(status, text="Hover:", bg=Theme.BG_PANEL, fg=Theme.FG_MUTED,
                font=FONT_SMALL).pack(side=tk.LEFT, padx=(8, 4))
        self.hover_label = tk.Label(status, text='--', bg=Theme.BG_PANEL,
                                   fg=Theme.FG_MUTED, width=16, anchor=tk.W,
                                   font=FONT_SMALL, padx=6)
        self.hover_label.pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="Hazir. Bir goruntu yukleyin.")
        tk.Label(status, textvariable=self.status_var, bg=Theme.BG_PANEL,
                fg=Theme.FG, font=FONT_SMALL).pack(side=tk.LEFT, padx=15)

        # ---------------- SAG: KONTROL ----------------
        control_frame = tk.Frame(main_paned, bg=Theme.BG, width=450)
        main_paned.add(control_frame, minsize=400)

        notebook = ttk.Notebook(control_frame)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Sekme 1: Eslesmeler + Palet (birlestirilmis)
        work_tab = tk.Frame(notebook, bg=Theme.BG_PANEL)
        notebook.add(work_tab, text="  Calisma Alani  ")
        self._build_work_tab(work_tab)

        # Sekma 2: Ayarlar
        settings_tab = tk.Frame(notebook, bg=Theme.BG_PANEL)
        notebook.add(settings_tab, text="  Ayarlar  ")
        self._build_settings_tab(settings_tab)

    # ============================================================
    # CALISMA ALANI SEKMESI (Eslesmeler + Palet)
    # ============================================================

    def _build_work_tab(self, parent):
        # Dikey PanedWindow: ust eslesmeler, alt palet
        paned = tk.PanedWindow(parent, orient=tk.VERTICAL,
                              bg=Theme.BG_PANEL, sashwidth=4,
                              sashrelief=tk.FLAT)
        paned.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ----- UST: KAYNAK RENK SECIMI + ESLESMELER -----
        top_frame = tk.Frame(paned, bg=Theme.BG_PANEL)
        paned.add(top_frame, minsize=200, height=400)

        # Kaynak renk secim alani
        src_frame = tk.LabelFrame(top_frame, text=" Kaynak Renk ",
                                 bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                 font=FONT_LARGE, bd=2,
                                 highlightbackground=Theme.BORDER,
                                 highlightthickness=1, padx=8, pady=8)
        src_frame.pack(fill=tk.X, padx=4, pady=4)

        # Ust satir: renk kutusu + RGB degeri + "fotodan sec" ipucu
        src_top = tk.Frame(src_frame, bg=Theme.BG_PANEL)
        src_top.pack(fill=tk.X)

        self.source_swatch = tk.Label(src_top, bg='#808080', width=4, height=2,
                                     relief=tk.SOLID, bd=1,
                                     highlightbackground=Theme.SWATCH_BORDER,
                                     highlightthickness=1)
        self.source_swatch.pack(side=tk.LEFT, padx=(0, 8))

        self.source_rgb_var = tk.StringVar(value="Henutz secilmedi\n"
                                                "(gorsele tikla veya asagidan ayarla)")
        tk.Label(src_top, textvariable=self.source_rgb_var, bg=Theme.BG_PANEL,
                fg=Theme.FG, font=FONT_NORMAL, justify=tk.LEFT).pack(side=tk.LEFT)

        # RGB slider'lari (kaynak rengi elle ayarlamak icin)
        rgb_frame = tk.Frame(src_frame, bg=Theme.BG_PANEL)
        rgb_frame.pack(fill=tk.X, pady=(8, 0))

        self.src_rgb_vars = [tk.IntVar(value=128), tk.IntVar(value=128),
                            tk.IntVar(value=128)]
        self.src_rgb_labels = []
        for i, ch in enumerate(['R', 'G', 'B']):
            row = tk.Frame(rgb_frame, bg=Theme.BG_PANEL)
            row.pack(fill=tk.X, pady=1)

            tk.Label(row, text=ch, bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                    font=FONT_NORMAL, width=2).pack(side=tk.LEFT)

            scale = tk.Scale(row, from_=0, to=255, orient=tk.HORIZONTAL,
                            variable=self.src_rgb_vars[i], showvalue=False,
                            bg=Theme.BG_PANEL, fg=Theme.FG, troughcolor=Theme.BG_INPUT,
                            highlightthickness=0, sliderrelief=tk.FLAT,
                            activebackground=Theme.ACCENT_DARK,
                            length=180, resolution=1,
                            command=lambda v, idx=i: self._on_src_rgb_change(idx))
            scale.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)

            # Sayisal deger kutusu (yukari/asagi oklu Spinbox)
            spin = tk.Spinbox(row, from_=0, to=255, increment=1, width=4,
                            textvariable=self.src_rgb_vars[i], font=FONT_SMALL,
                            bg=Theme.BG_INPUT, fg=Theme.FG, relief=tk.FLAT,
                            buttonbackground=Theme.BG_HOVER,
                            buttonuprelief=tk.FLAT, buttondownrelief=tk.FLAT,
                            highlightthickness=0, bd=0,
                            command=lambda idx=i: self._on_src_rgb_spin(idx))
            spin.pack(side=tk.LEFT, padx=(4, 0))
            self.src_rgb_labels.append(spin)

        # "Kaynak olarak kullan" butonu
        tk.Button(src_frame, text="Bu rengi kaynak olarak kullan",
                 bg=Theme.ACCENT, fg=Theme.BG, font=FONT_NORMAL,
                 relief=tk.FLAT, padx=10, pady=4,
                 activebackground=Theme.ACCENT_DARK, activeforeground=Theme.BG,
                 command=self._use_rgb_as_source).pack(pady=(8, 0))

        # Eslesmeler listesi
        list_frame = tk.LabelFrame(top_frame, text=" Eslesmeler ",
                                  bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                  font=FONT_LARGE, bd=2,
                                  highlightbackground=Theme.BORDER,
                                  highlightthickness=1, padx=8, pady=8)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Eslesme satirlari scrollable
        list_canvas_frame = tk.Frame(list_frame, bg=Theme.BG_PANEL)
        list_canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.list_canvas = tk.Canvas(list_canvas_frame, bg=Theme.BG_PANEL,
                                    highlightthickness=0, height=150)
        list_scroll = ttk.Scrollbar(list_canvas_frame, orient=tk.VERTICAL,
                                    command=self.list_canvas.yview)
        self.list_inner = tk.Frame(self.list_canvas, bg=Theme.BG_PANEL)
        self.list_inner.bind(
            "<Configure>",
            lambda e: self.list_canvas.configure(scrollregion=self.list_canvas.bbox("all"))
        )
        self.list_window_id = self.list_canvas.create_window(
            (0, 0), window=self.list_inner, anchor="nw"
        )
        self.list_canvas.bind(
            "<Configure>",
            lambda e: self.list_canvas.itemconfig(self.list_window_id, width=e.width)
        )
        self.list_canvas.configure(yscrollcommand=list_scroll.set)
        self.list_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.list_canvas.bind_all("<MouseWheel>",
            lambda e: self.list_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        # Liste kontrol butonlari
        list_btn = tk.Frame(list_frame, bg=Theme.BG_PANEL)
        list_btn.pack(fill=tk.X, pady=(4, 0))
        tk.Button(list_btn, text="Secili Sil", bg=Theme.DANGER, fg=Theme.BG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=8, pady=4,
                 activebackground='#c46a82', activeforeground=Theme.BG,
                 command=self.delete_mapping).pack(side=tk.LEFT, padx=2)
        tk.Button(list_btn, text="Tumunu Sil", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=8, pady=4,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.clear_mappings).pack(side=tk.LEFT, padx=2)
        tk.Button(list_btn, text="Kaydet", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=8, pady=4,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.save_mappings).pack(side=tk.RIGHT, padx=2)
        tk.Button(list_btn, text="Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=8, pady=4,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_mappings).pack(side=tk.RIGHT, padx=2)

        # ----- ALT: PALET -----
        bot_frame = tk.Frame(paned, bg=Theme.BG_PANEL)
        paned.add(bot_frame, minsize=200, height=300)

        pal_frame = tk.LabelFrame(bot_frame, text=" Palet (hedef icin tikla) ",
                                 bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                 font=FONT_LARGE, bd=2,
                                 highlightbackground=Theme.BORDER,
                                 highlightthickness=1, padx=8, pady=8)
        pal_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Palet kontrol
        pal_ctrl = tk.Frame(pal_frame, bg=Theme.BG_PANEL)
        pal_ctrl.pack(fill=tk.X, pady=(0, 6))
        tk.Button(pal_ctrl, text=".gpl Yukle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_SMALL, relief=tk.FLAT, padx=6, pady=3,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.load_palette_gpl).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text=".gpl Kaydet", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_SMALL, relief=tk.FLAT, padx=6, pady=3,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.save_palette_gpl).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text="RGB Ekle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_SMALL, relief=tk.FLAT, padx=6, pady=3,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.add_color_manual).pack(side=tk.LEFT, padx=2)
        tk.Button(pal_ctrl, text="Temizle", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_SMALL, relief=tk.FLAT, padx=6, pady=3,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=self.clear_palette).pack(side=tk.LEFT, padx=2)
        self.palette_info_var = tk.StringVar(value="0 renk")
        tk.Label(pal_ctrl, textvariable=self.palette_info_var, bg=Theme.BG_PANEL,
                fg=Theme.FG_MUTED, font=FONT_SMALL).pack(side=tk.RIGHT, padx=4)

        # Palet scrollable
        pal_canvas_frame = tk.Frame(pal_frame, bg=Theme.BG_PANEL)
        pal_canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.palette_canvas = tk.Canvas(pal_canvas_frame, bg=Theme.BG_PANEL,
                                       highlightthickness=0)
        pal_scroll = ttk.Scrollbar(pal_canvas_frame, orient=tk.VERTICAL,
                                   command=self.palette_canvas.yview)
        self.palette_inner = tk.Frame(self.palette_canvas, bg=Theme.BG_PANEL)
        self.palette_inner.bind(
            "<Configure>",
            lambda e: self.palette_canvas.configure(
                scrollregion=self.palette_canvas.bbox("all"))
        )
        self.palette_window_id = self.palette_canvas.create_window(
            (0, 0), window=self.palette_inner, anchor="nw"
        )
        self.palette_canvas.bind(
            "<Configure>",
            lambda e: self.palette_canvas.itemconfig(
                self.palette_window_id, width=e.width)
        )
        self.palette_canvas.configure(yscrollcommand=pal_scroll.set)
        self.palette_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pal_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ============================================================
    # AYARLAR SEKMESI
    # ============================================================

    def _build_settings_tab(self, parent):
        container = tk.Frame(parent, bg=Theme.BG_PANEL, padx=20, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        # Mod secimi
        mode_frame = tk.LabelFrame(container, text=" Mod ", bg=Theme.BG_PANEL,
                                  fg=Theme.ACCENT, font=FONT_LARGE, bd=2,
                                  highlightbackground=Theme.BORDER,
                                  highlightthickness=1, padx=12, pady=10)
        mode_frame.pack(fill=tk.X, pady=6)

        self.mode_var = tk.StringVar(value='single')
        tk.Radiobutton(mode_frame, text="  Tek Kaydirici (Tension)",
                      variable=self.mode_var, value='single',
                      bg=Theme.BG_PANEL, fg=Theme.FG, selectcolor=Theme.BG_INPUT,
                      activebackground=Theme.BG_PANEL, activeforeground=Theme.FG,
                      font=FONT_NORMAL, command=self.on_mode_change,
                      highlightthickness=0, bd=0).pack(anchor=tk.W, pady=2)
        tk.Radiobutton(mode_frame, text="  Cift Kaydirici (Softness + Snap)",
                      variable=self.mode_var, value='dual',
                      bg=Theme.BG_PANEL, fg=Theme.FG, selectcolor=Theme.BG_INPUT,
                      activebackground=Theme.BG_PANEL, activeforeground=Theme.FG,
                      font=FONT_NORMAL, command=self.on_mode_change,
                      highlightthickness=0, bd=0).pack(anchor=tk.W, pady=2)

        # Tek slider alani
        self.single_frame = tk.LabelFrame(container, text=" Tek Kaydirici Modu ",
                                         bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                         font=FONT_LARGE, bd=2,
                                         highlightbackground=Theme.BORDER,
                                         highlightthickness=1, padx=12, pady=10)
        self.single_frame.pack(fill=tk.X, pady=6)
        self._add_slider(self.single_frame, "Tension (Gerginlik)",
                        'tension', 0.0, 1.0, 0.5,
                        "0 = yumusak gecisler, 1 = siki palet")

        # Cift slider alani
        self.dual_frame = tk.LabelFrame(container, text=" Cift Kaydirici Modu ",
                                       bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                       font=FONT_LARGE, bd=2,
                                       highlightbackground=Theme.BORDER,
                                       highlightthickness=1, padx=12, pady=10)
        self.dual_frame.pack(fill=tk.X, pady=6)
        self._add_slider(self.dual_frame, "Softness (Etki Genisligi)",
                        'softness', 0.0, 1.0, 0.5,
                        "0 = dar etki, 1 = genis etki")
        self._add_slider(self.dual_frame, "Snap (Palet Yapismasi)",
                        'snap', 0.0, 1.0, 0.0,
                        "0 = yapismasiz, 1 = tam palet yapismasi")

        # Etki gucu
        str_frame = tk.LabelFrame(container, text=" Etki Gucu (tum modlarda) ",
                                 bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                 font=FONT_LARGE, bd=2,
                                 highlightbackground=Theme.BORDER,
                                 highlightthickness=1, padx=12, pady=10)
        str_frame.pack(fill=tk.X, pady=6)
        self._add_slider(str_frame, "Strength (Opaklik)", 'strength',
                        0.0, 1.0, 1.0,
                        "0 = orijinal, 1 = tam donusum")

        # Bilgi
        info_frame = tk.LabelFrame(container, text=" Nasil Kullanilir? ",
                                  bg=Theme.BG_PANEL, fg=Theme.ACCENT,
                                  font=FONT_LARGE, bd=2,
                                  highlightbackground=Theme.BORDER,
                                  highlightthickness=1, padx=12, pady=10)
        info_frame.pack(fill=tk.BOTH, expand=True, pady=6)
        info_text = (
            "1. Goruntu Yukle'ye bas.\n"
            "2. Gorsele tikla (kaynak renk secer)\n"
            "   veya RGB slider'lariyla elle ayarla.\n"
            "3. Paletten bir renge tikla (hedef).\n"
            "4. Birkac nokta icin tekrarla.\n"
            "5. Ayarlar'dan gerginligi ayarla.\n"
            "6. 'Onizle' butonuna bas -> canli mod acilir.\n"
            "7. Slider'lari oynayinca anlik sonuc gorursun.\n"
            "8. Yeni eslesme eklersen canli mod kapanir.\n"
            "9. 'Sonucu Kaydet' ile bitir."
        )
        tk.Label(info_frame, text=info_text, justify=tk.LEFT,
                bg=Theme.BG_PANEL, fg=Theme.FG, font=FONT_NORMAL).pack(
                    anchor=tk.W, padx=8, pady=8)

        self.on_mode_change()

    def _add_slider(self, parent, label, var_name, vmin, vmax, default, hint):
        """Standart slider + deger etiketi ekler."""
        # Label
        tk.Label(parent, text=label, bg=Theme.BG_PANEL, fg=Theme.FG,
                font=FONT_NORMAL, anchor=tk.W).pack(fill=tk.X, pady=(6, 0))

        # Slider satiri
        row = tk.Frame(parent, bg=Theme.BG_PANEL)
        row.pack(fill=tk.X, pady=2)

        # Variable
        var = tk.DoubleVar(value=default)
        setattr(self, f"{var_name}_var", var)

        # Value label (slider solunda)
        val_label = tk.Label(row, text=f"{default:.2f}", width=6,
                            bg=Theme.BG_PANEL, fg=Theme.ACCENT, font=FONT_NORMAL,
                            anchor=tk.E)
        val_label.pack(side=tk.LEFT, padx=(0, 6))
        setattr(self, f"{var_name}_value_label", val_label)

        # Slider (tk.Scale — tkk.Scale'ten daha az savrulma)
        scale = tk.Scale(row, from_=vmin, to=vmax, orient=tk.HORIZONTAL,
                        variable=var, showvalue=False,
                        bg=Theme.BG_PANEL, fg=Theme.FG,
                        troughcolor=Theme.BG_INPUT, highlightthickness=0,
                        sliderrelief=tk.FLAT, activebackground=Theme.ACCENT_DARK,
                        length=200, resolution=0.01,
                        command=lambda v, n=var_name: self._on_slider_change(n))
        scale.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)

        # Hint
        tk.Label(parent, text=hint, bg=Theme.BG_PANEL, fg=Theme.FG_MUTED,
                font=FONT_SMALL, anchor=tk.W).pack(fill=tk.X, pady=(0, 6))

    def _on_slider_change(self, name):
        """Slider degeri degisti — deger etiketini guncelle + canli onizleme."""
        var = getattr(self, f"{name}_var")
        label = getattr(self, f"{name}_value_label")
        label.config(text=f"{var.get():.2f}")
        # Canli onizleme varsa debounce ile yenile
        if self.preview_mode:
            self._schedule_live_preview()

    def _schedule_live_preview(self):
        """Debounce: 200ms bekleyip onizlemeyi yenile."""
        if self.preview_job is not None:
            self.root.after_cancel(self.preview_job)
        self.preview_job = self.root.after(200, self._do_live_preview)

    def _do_live_preview(self):
        """Canli onizlemeyi guncelle (ayni eslesmeler, yeni ayarlar)."""
        if not self.preview_mode or self.image_array is None:
            return
        if not self.mappings:
            return
        # Thread'de calistir ki UI kitlenmesin
        t = threading.Thread(target=self._live_preview_thread, daemon=True)
        t.start()

    def _live_preview_thread(self):
        """Arka plan: onizleme hesapla ve UI'i guncelle."""
        with self.preview_lock:
            try:
                warp = self._build_warp_internal()
                if warp is None:
                    return
                # Kucuk çözünürlükte hesapla (hiz icin)
                preview_arr = self._compute_preview(warp)
                if preview_arr is None:
                    return
                self.preview_array = preview_arr
                # UI guncellemesi ana thread'de yapilmali
                self.root.after(0, lambda: self._display_array(preview_arr))
            except Exception as e:
                print(f"Live preview hatasi: {e}")

    def _compute_preview(self, warp):
        """Onizleme icin dusuk cozunurlukte hesapla."""
        if self.image_array is None:
            return None
        H, W = self.image_array.shape[:2]
        # 800 pikseli gecmeyen onizleme
        max_dim = 800
        if max(H, W) > max_dim:
            scale = max_dim / max(H, W)
            small_h, small_w = int(H * scale), int(W * scale)
            small_img = Image.fromarray(self.image_array).resize(
                (small_w, small_h), Image.LANCZOS)
            small_arr = np.array(small_img)
            result_small = warp.apply(small_arr, strength=self.strength_var.get())
            return result_small
        else:
            return warp.apply(self.image_array, strength=self.strength_var.get())

    def on_mode_change(self):
        if self.mode_var.get() == 'single':
            self.dual_frame.pack_forget()
            self.single_frame.pack(fill=tk.X, pady=6,
                                   after=self._find_after_widget())
        else:
            self.single_frame.pack_forget()
            self.dual_frame.pack(fill=tk.X, pady=6,
                                after=self._find_after_widget())
        if self.preview_mode:
            self._schedule_live_preview()

    def _find_after_widget(self):
        """Mod frame'ini bul, onun altina yerlestir."""
        # Bu fonksiyon mod frame'ini dondurur — basit tutmak icin
        # _build_settings_tab icindeki mode_frame'i kullanir
        return getattr(self, '_mode_frame_ref', None)

    # ============================================================
    # GORUNTU YUKLEME
    # ============================================================

    def load_image(self):
        path = filedialog.askopenfilename(
            title="Goruntu sec",
            filetypes=[("Goruntu", "*.jpg *.jpeg *.png *.bmp *.tiff *.webp"),
                       ("Tum dosyalar", "*.*")])
        if not path:
            return
        try:
            img = Image.open(path).convert('RGB')
            self.original_image = img
            self.image_array = np.array(img)
            self.preview_mode = False
            self.preview_array = None
            self.zoom_factor = 1.0
            self._display_image(img)
            self.status_var.set(f"Yuklendi: {Path(path).name}  "
                                f"({img.width}x{img.height})")
        except Exception as e:
            messagebox.showerror("Hata", f"Goruntu yuklenemedi:\n{e}")

    def _display_image(self, pil_image):
        # Ekrana sigdir + zoom uygula
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
        """Numpy array'i goruntule."""
        pil = Image.fromarray(arr)
        self._display_image(pil)

    def _update_zoom_label(self):
        pct = int(self.zoom_factor * 100)
        self.zoom_var.set(f"Zoom: {pct}%")

    def show_original(self):
        if self.original_image is None:
            messagebox.showwarning("Uyari", "Once bir goruntu yukleyin.")
            return
        self.preview_mode = False
        self._display_image(self.original_image)
        self.status_var.set("Orijinal gosteriliyor.")

    def toggle_preview(self):
        """Onizle'ye basildi — canli modu ac/kapat."""
        if self.image_array is None:
            messagebox.showwarning("Uyari", "Once bir goruntu yukleyin.")
            return
        if not self.mappings:
            messagebox.showwarning("Uyari",
                "Hic eslesme yok. Once birkac nokta secin.")
            return
        if self.preview_mode:
            # Zaten acik — kapat ve orijinali goster
            self.preview_mode = False
            self._display_image(self.original_image)
            self.status_var.set("Canli onizleme kapandi.")
        else:
            # Ac
            self.preview_mode = True
            self.status_var.set("Canli onizleme acik. Slider'lari oynayinca "
                                "sonuc anlik guncellenir.")
            self._schedule_live_preview()

    # ============================================================
    # ZOOM
    # ============================================================

    def on_mouse_wheel(self, event):
        """Windows/Mac: delta degeri ile zoom."""
        if event.delta > 0:
            factor = 1.15
        else:
            factor = 0.87
        self._zoom_at(event.x, event.y, factor)

    def _zoom_at(self, x, y, factor):
        """Verilen canvas koordinatinda zoom yap."""
        if self.original_image is None:
            return
        old_zoom = self.zoom_factor
        new_zoom = old_zoom * factor
        # Sinirlar
        new_zoom = max(0.1, min(10.0, new_zoom))
        if new_zoom == old_zoom:
            return
        self.zoom_factor = new_zoom

        # Hangi goruntu goruntuleniyor?
        if self.preview_mode and self.preview_array is not None:
            pil = Image.fromarray(self.preview_array)
        else:
            pil = self.original_image
        self._display_image(pil)
        # TODO: konum kaydirma ( Fare etrafinda zoom )

    # ============================================================
    # DAMLALIK
    # ============================================================

    def on_canvas_click(self, event):
        if self.image_array is None:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        total_scale = self.base_scale * self.zoom_factor
        ox = int(cx / total_scale)
        oy = int(cy / total_scale)
        H, W = self.image_array.shape[:2]
        if not (0 <= ox < W and 0 <= oy < H):
            return
        pixel = self.image_array[oy, ox]
        rgb = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
        self._set_source_color(rgb, from_image=True, pos=(ox, oy))

    def on_canvas_motion(self, event):
        if self.image_array is None:
            return
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        total_scale = self.base_scale * self.zoom_factor
        ox = int(cx / total_scale)
        oy = int(cy / total_scale)
        H, W = self.image_array.shape[:2]
        if not (0 <= ox < W and 0 <= oy < H):
            return
        pixel = self.image_array[oy, ox]
        rgb = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
        hex_c = '#%02x%02x%02x' % rgb
        fg = 'white' if sum(rgb) < 384 else 'black'
        self.hover_label.config(text=f"  RGB {rgb}  ", bg=hex_c, fg=fg)

    def _set_source_color(self, rgb, from_image=False, pos=None):
        """Kaynak rengi ayarla (UI guncelle)."""
        self.picked_source = rgb
        hex_c = '#%02x%02x%02x' % rgb
        self.source_swatch.config(bg=hex_c)
        if from_image and pos:
            self.source_rgb_var.set(
                f"RGB: {rgb}\nKonum: ({pos[0]}, {pos[1]})\n-> Paletten hedef sec")
        else:
            self.source_rgb_var.set(
                f"RGB: {rgb}\n(Elle ayarlandi)\n-> Paletten hedef sec")
        # RGB slider'lari senkronize et
        for i, v in enumerate(rgb):
            self.src_rgb_vars[i].set(v)
        self.status_var.set(f"Kaynak secildi: {rgb}. "
                            f"Simdi paletten hedef renge tiklayin.")

    def _on_src_rgb_change(self, idx):
        """RGB slider degisti — swatch guncelle, picked_source guncelle."""
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
        self.source_rgb_var.set(f"RGB: {rgb}\n(Elle ayarlandi)\n"
                                f"-> Paletten hedef sec")

    def _on_src_rgb_spin(self, idx):
        """Spinbox'tan degisti."""
        self._on_src_rgb_change(idx)

    def _use_rgb_as_source(self):
        """Buton: bu rengi kaynak olarak kullan."""
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
            (0, 0, 0), (64, 64, 64), (128, 128, 128), (192, 192, 192), (255, 255, 255),
            (255, 0, 0), (255, 128, 0), (255, 255, 0), (128, 255, 0), (0, 255, 0),
            (0, 255, 128), (0, 255, 255), (0, 128, 255), (0, 0, 255), (128, 0, 255),
            (255, 0, 255), (255, 0, 128), (128, 64, 0), (200, 160, 120), (255, 220, 180),
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
            sw = tk.Label(self.palette_inner, bg=hex_c, width=6, height=3,
                         relief=tk.FLAT, bd=0,
                         highlightbackground=Theme.SWATCH_BORDER,
                         highlightthickness=1, cursor='hand2')
            sw.grid(row=r, column=c, padx=2, pady=2, sticky='nsew')
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
                "Once kaynak renk secin (gorsele tikla veya RGB ayarla),\n"
                "sonra paletten hedef renge tiklayin.")
            return
        self.mappings.append({"src": self.picked_source, "dst": color})
        self._refresh_mappings_list()
        # Yeni eslesme eklendi -> canli modu kapat
        if self.preview_mode:
            self.preview_mode = False
            self._display_image(self.original_image)
            self.status_var.set(f"Eslesme eklendi (toplam {len(self.mappings)}). "
                                f"Canli mod kapandi. Onizle'ye bas.")
        else:
            self.status_var.set(f"Eslesme eklendi. Toplam: {len(self.mappings)} nokta.")
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
        dlg.geometry("320x250")
        dlg.transient(self.root)
        dlg.configure(bg=Theme.BG_PANEL)

        tk.Label(dlg, text="Yeni palet rengi ekle", bg=Theme.BG_PANEL,
                fg=Theme.ACCENT, font=FONT_LARGE).pack(pady=10)

        entries = []
        for i, ch in enumerate(['R', 'G', 'B']):
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
                 font=FONT_NORMAL, relief=tk.FLAT, padx=12, pady=4,
                 activebackground=Theme.ACCENT_DARK, activeforeground=Theme.BG,
                 command=on_ok).pack(side=tk.LEFT, padx=4)
        tk.Button(btns, text="Iptal", bg=Theme.BG_INPUT, fg=Theme.FG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=12, pady=4,
                 activebackground=Theme.BG_HOVER, activeforeground=Theme.FG,
                 command=dlg.destroy).pack(side=tk.LEFT, padx=4)

    def clear_palette(self):
        if messagebox.askyesno("Onay", "Paleti temizlemek istediginize emin misiniz?"):
            self.palette.clear()
            self._render_palette()

    def load_palette_gpl(self):
        path = filedialog.askopenfilename(
            title="Palet sec (.gpl)",
            filetypes=[("GIMP Palette", "*.gpl"), ("Tum dosyalar", "*.*")])
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
        path = filedialog.asksaveasfilename(
            title="Palet kaydet", defaultextension=".gpl",
            filetypes=[("GIMP Palette", "*.gpl")])
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
    # ESLESME LISTESI (Ozel satir widget'lari)
    # ============================================================

    def _refresh_mappings_list(self):
        # Eski satirlari temizle
        for w in self.mapping_widgets:
            w.destroy()
        self.mapping_widgets.clear()
        # Yeni satirlar
        for i, m in enumerate(self.mappings):
            row = self._build_mapping_row(self.list_inner, i, m)
            row.pack(fill=tk.X, padx=2, pady=2)
            self.mapping_widgets.append(row)

    def _build_mapping_row(self, parent, idx, mapping):
        """Tek bir eslesme satiri: [kaynak kutusu] -> [hedef kutusu] [sil]"""
        row = tk.Frame(parent, bg=Theme.BG_INPUT, bd=0,
                      highlightbackground=Theme.BORDER, highlightthickness=1)
        # Kaynak renk kutusu
        src = mapping["src"]
        dst = mapping["dst"]
        src_hex = '#%02x%02x%02x' % src
        dst_hex = '#%02x%02x%02x' % dst

        tk.Label(row, bg=src_hex, width=4, height=2, relief=tk.FLAT,
                highlightbackground=Theme.SWATCH_BORDER, highlightthickness=1).pack(
                    side=tk.LEFT, padx=4, pady=4)
        tk.Label(row, text=f"{src}", bg=Theme.BG_INPUT, fg=Theme.FG,
                font=FONT_SMALL, width=14).pack(side=tk.LEFT, padx=2)

        # Ok
        tk.Label(row, text="  ->  ", bg=Theme.BG_INPUT, fg=Theme.ACCENT,
                font=FONT_LARGE).pack(side=tk.LEFT, padx=2)

        tk.Label(row, bg=dst_hex, width=4, height=2, relief=tk.FLAT,
                highlightbackground=Theme.SWATCH_BORDER, highlightthickness=1).pack(
                    side=tk.LEFT, padx=4, pady=4)
        tk.Label(row, text=f"{dst}", bg=Theme.BG_INPUT, fg=Theme.FG,
                font=FONT_SMALL, width=14).pack(side=tk.LEFT, padx=2)

        # Sil butonu
        tk.Button(row, text="X", bg=Theme.DANGER, fg=Theme.BG,
                 font=FONT_NORMAL, relief=tk.FLAT, padx=6, pady=2,
                 activebackground='#c46a82', activeforeground=Theme.BG,
                 command=lambda i=idx: self._delete_mapping_by_idx(i)).pack(
                     side=tk.RIGHT, padx=4, pady=4)

        return row

    def _delete_mapping_by_idx(self, idx):
        if 0 <= idx < len(self.mappings):
            del self.mappings[idx]
            self._refresh_mappings_list()
            if self.preview_mode:
                self._schedule_live_preview()
            self.status_var.set(f"Silindi. Toplam: {len(self.mappings)} nokta.")

    def delete_mapping(self):
        # Bu fonksiyon artik kullanilmiyor (her satirda kendi sil butonu var)
        # ama eski cagrilardan dolayi tutuyoruz
        messagebox.showinfo("Bilgi", "Silmek istediginiz satirdaki 'X' butonuna basın.")

    def clear_mappings(self):
        if messagebox.askyesno("Onay", "Tum eslesmeleri silmek istediginize emin misiniz?"):
            self.mappings.clear()
            self._refresh_mappings_list()
            if self.preview_mode:
                self.preview_mode = False
                self._display_image(self.original_image)

    def save_mappings(self):
        if not self.mappings:
            messagebox.showwarning("Uyari", "Kaydedilecek eslesme yok.")
            return
        path = filedialog.asksaveasfilename(
            title="Eslesmeleri kaydet", defaultextension=".json",
            filetypes=[("JSON", "*.json")])
        if not path:
            return
        data = {"points": [{"src": list(m["src"]), "dst": list(m["dst"])}
                          for m in self.mappings]}
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.status_var.set(f"Eslesmeler kaydedildi: {path}")

    def load_mappings(self):
        path = filedialog.askopenfilename(
            title="Eslesme dosyasi sec",
            filetypes=[("JSON", "*.json"), ("Tum dosyalar", "*.*")])
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            points = data.get('points', data) if isinstance(data, dict) else data
            self.mappings = [{"src": tuple(p["src"]), "dst": tuple(p["dst"])}
                           for p in points]
            self._refresh_mappings_list()
            self.status_var.set(f"Eslesmeler yuklendi: {len(self.mappings)} nokta.")
        except Exception as e:
            messagebox.showerror("Hata", f"Yuklenemedi:\n{e}")

    # ============================================================
    # DONUSUM
    # ============================================================

    def _build_warp_internal(self):
        if not self.mappings:
            return None
        src = [m["src"] for m in self.mappings]
        tgt = [m["dst"] for m in self.mappings]
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

    def save_result(self):
        if self.image_array is None:
            messagebox.showwarning("Uyari", "Once bir goruntu yukleyin.")
            return
        if not self.mappings:
            messagebox.showwarning("Uyari", "Hic eslesme yok.")
            return
        # Tam cozunurlukte hesapla
        warp = self._build_warp_internal()
        if warp is None:
            return
        path = filedialog.asksaveasfilename(
            title="Sonucu kaydet", defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("TIFF", "*.tiff")])
        if not path:
            return
        try:
            self.status_var.set("Hesaplaniyor (tam cozunurluk)...")
            self.root.update()
            result = warp.apply(self.image_array, strength=self.strength_var.get())
            Image.fromarray(result).save(path)
            self.status_var.set(f"Kaydedildi: {path}")
            messagebox.showinfo("Tamam", f"Sonuc kaydedildi:\n{path}")
        except Exception as e:
            messagebox.showerror("Hata", f"Kaydedilemedi:\n{e}")


# ============================================================
# GIRIS
# ============================================================

def main():
    root = tk.Tk()
    app = RecolorGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
