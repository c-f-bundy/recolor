#!/usr/bin/env python3
"""
Recolor GUI - Renk Standardizasyon Araci

Pencere tabanli arayuz. Damlalikla piksel sec, paletten hedef renk sec,
onizle, kaydet.

Kullanim:
    python3 recolor_gui.py

Gereksinimler:
    pip install numpy Pillow scikit-image
    (Tkinter Python ile birlikte gelir, ekstra kurulum gerekmez)
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageTk

# Ayni klasordeki cekirdek modulu ice aktar
sys.path.insert(0, str(Path(__file__).parent))
from recolor_core import ColorWarp


# ============================================================
# ANA PENCERE SINIFI
# ============================================================

class RecolorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Recolor - Renk Standardizasyon Araci")
        self.root.geometry("1300x850")
        self.root.minsize(900, 600)

        # --- Durum ---
        self.original_image = None        # PIL Image (orijinal)
        self.image_array = None           # numpy array (H, W, 3) uint8
        self.display_photo = None         # ImageTk.PhotoImage (goruntulenem)
        self.scale_factor = 1.0           # orijinal -> goruntuleme olcegi
        self.palette = []                 # [(r,g,b), ...] palet renkleri
        self.palette_swatches = []        # tk.Label widget listesi
        self.mappings = []                # [{"src":(r,g,b), "dst":(r,g,b)}, ...]
        self.picked_source = None         # (r,g,b) veya None
        self.preview_array = None         # onizleme numpy array
        self.showing_preview = False
        self.hover_color_label = None     # hover rengi gosteren label

        self._build_ui()
        self._setup_default_palette()

    # ============================================================
    # UI INSAASI
    # ============================================================

    def _build_ui(self):
        # Ust menu cubugu
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Goruntu Yukle", command=self.load_image)
        file_menu.add_command(label="Palet Yukle (.gpl)", command=self.load_palette_gpl)
        file_menu.add_command(label="Palet Kaydet (.gpl)", command=self.save_palette_gpl)
        file_menu.add_command(label="Eslesmeleri Kaydet (JSON)", command=self.save_mappings)
        file_menu.add_command(label="Eslesmeleri Yukle (JSON)", command=self.load_mappings)
        file_menu.add_separator()
        file_menu.add_command(label="Cikis", command=self.root.quit)
        menubar.add_cascade(label="Dosya", menu=file_menu)

        # Ana yerlesim: sol goruntu + sag kontrol paneli
        main_paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        main_paned.pack(fill=tk.BOTH, expand=True)

        # ---------------- SOL: GORUNTU ALANI ----------------
        image_frame = ttk.Frame(main_paned)
        main_paned.add(image_frame, weight=3)

        # Goruntu canvasi (kaydirma cubuklari ile)
        canvas_frame = ttk.Frame(image_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg='#303030', cursor='crosshair')
        h_scroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        v_scroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=h_scroll.set, yscrollcommand=v_scroll.set)

        self.canvas.grid(row=0, column=0, sticky='nsew')
        h_scroll.grid(row=1, column=0, sticky='ew')
        v_scroll.grid(row=0, column=1, sticky='ns')
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas.bind('<Button-1>', self.on_canvas_click)
        self.canvas.bind('<Motion>', self.on_canvas_motion)
        self.canvas.bind('<Leave>', lambda e: self.hover_label.config(text='--'))

        # Goruntu kontrol cubuklari
        ctrl = ttk.Frame(image_frame)
        ctrl.pack(fill=tk.X, pady=4)
        ttk.Button(ctrl, text="Goruntu Yukle", command=self.load_image).pack(side=tk.LEFT, padx=3)
        ttk.Button(ctrl, text="Onizle", command=self.preview).pack(side=tk.LEFT, padx=3)
        ttk.Button(ctrl, text="Orijinali Goster", command=self.show_original).pack(side=tk.LEFT, padx=3)
        ttk.Button(ctrl, text="Sonucu Kaydet", command=self.save_result).pack(side=tk.LEFT, padx=3)

        # Durum cubugu
        status_frame = ttk.Frame(image_frame)
        status_frame.pack(fill=tk.X, pady=2)
        ttk.Label(status_frame, text="Hover:").pack(side=tk.LEFT, padx=(5, 2))
        self.hover_label = tk.Label(status_frame, text='--', bg='#606060', fg='white',
                                    width=12, relief=tk.SUNKEN, padx=5)
        self.hover_label.pack(side=tk.LEFT, padx=2)
        self.status_var = tk.StringVar(value="Hazir. Bir goruntu yukleyin.")
        ttk.Label(status_frame, textvariable=self.status_var).pack(side=tk.LEFT, padx=10)

        # ---------------- SAG: KONTROL PANELI ----------------
        control_frame = ttk.Frame(main_paned)
        main_paned.add(control_frame, weight=1)

        notebook = ttk.Notebook(control_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Sekme 1: Eslesmeler
        mappings_tab = ttk.Frame(notebook)
        notebook.add(mappings_tab, text=" Eslesmeler ")
        self._build_mappings_tab(mappings_tab)

        # Sekma 2: Palet
        palette_tab = ttk.Frame(notebook)
        notebook.add(palette_tab, text=" Palet ")
        self._build_palette_tab(palette_tab)

        # Sekma 3: Ayarlar
        settings_tab = ttk.Frame(notebook)
        notebook.add(settings_tab, text=" Ayarlar ")
        self._build_settings_tab(settings_tab)

    def _build_mappings_tab(self, parent):
        # Secilen kaynak renk kutucugu
        pick_frame = ttk.LabelFrame(parent, text="Secili Kaynak Renk (gorsele tiklayin)")
        pick_frame.pack(fill=tk.X, padx=5, pady=5)

        self.source_color_label = tk.Label(pick_frame, bg='#808080', width=6, height=3,
                                           relief=tk.SUNKEN, borderwidth=2)
        self.source_color_label.pack(side=tk.LEFT, padx=5, pady=5)

        info_frame = ttk.Frame(pick_frame)
        info_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.source_rgb_var = tk.StringVar(value="Henutz secilmedi")
        ttk.Label(info_frame, textvariable=self.source_rgb_var).pack(anchor=tk.W)
        ttk.Label(info_frame, text="Paletten bir renge tiklayin =\neslesmeler listesine eklenir.",
                  foreground='#666').pack(anchor=tk.W)

        ttk.Button(pick_frame, text="Temizle", command=self.clear_source).pack(side=tk.RIGHT, padx=5)

        # Eslesme listesi
        list_frame = ttk.LabelFrame(parent, text="Eslesme Listesi")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        cols = ("src", "arrow", "dst")
        self.mappings_tree = ttk.Treeview(list_frame, columns=cols, show='headings', height=12)
        self.mappings_tree.heading('src', text='Kaynak (goruntuden)')
        self.mappings_tree.heading('arrow', text='->')
        self.mappings_tree.heading('dst', text='Hedef (paletten)')
        self.mappings_tree.column('src', width=120, anchor=tk.CENTER)
        self.mappings_tree.column('arrow', width=30, anchor=tk.CENTER)
        self.mappings_tree.column('dst', width=120, anchor=tk.CENTER)
        self.mappings_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        list_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.mappings_tree.yview)
        self.mappings_tree.configure(yscrollcommand=list_scroll.set)
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Eslesme butonlari
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(btn_frame, text="Secili Sil", command=self.delete_mapping).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Tumunu Sil", command=self.clear_mappings).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Kaydet", command=self.save_mappings).pack(side=tk.RIGHT, padx=2)
        ttk.Button(btn_frame, text="Yukle", command=self.load_mappings).pack(side=tk.RIGHT, padx=2)

    def _build_palette_tab(self, parent):
        # Palet kontrol cubuklari
        ctrl = ttk.Frame(parent)
        ctrl.pack(fill=tk.X, padx=5, pady=5)
        ttk.Button(ctrl, text=".gpl Yukle", command=self.load_palette_gpl).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text=".gpl Kaydet", command=self.save_palette_gpl).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text="RGB Ekle", command=self.add_color_manual).pack(side=tk.LEFT, padx=2)
        ttk.Button(ctrl, text="Temizle", command=self.clear_palette).pack(side=tk.LEFT, padx=2)

        # Palet bilgisi
        self.palette_info_var = tk.StringVar(value="0 renk")
        ttk.Label(parent, textvariable=self.palette_info_var).pack(anchor=tk.W, padx=5)

        # Palet goruntuleme (kaydirilabilir)
        palette_frame = ttk.LabelFrame(parent, text="Palet (hedef secmek icin tiklayin)")
        palette_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.palette_canvas = tk.Canvas(palette_frame, bg='#202020', highlightthickness=0)
        palette_scroll = ttk.Scrollbar(palette_frame, orient=tk.VERTICAL,
                                       command=self.palette_canvas.yview)
        self.palette_inner = ttk.Frame(self.palette_canvas)

        self.palette_inner.bind(
            "<Configure>",
            lambda e: self.palette_canvas.configure(scrollregion=self.palette_canvas.bbox("all"))
        )
        self.palette_window_id = self.palette_canvas.create_window(
            (0, 0), window=self.palette_inner, anchor="nw"
        )
        self.palette_canvas.bind(
            "<Configure>",
            lambda e: self.palette_canvas.itemconfig(
                self.palette_window_id, width=e.width
            )
        )
        self.palette_canvas.configure(yscrollcommand=palette_scroll.set)

        self.palette_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        palette_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Mouse tekerlegi ile kaydirma
        self.palette_canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.palette_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        )

    def _build_settings_tab(self, parent):

        # Mod secimi
        self.mode_frame = ttk.LabelFrame(parent, text="Mod")
        self.mode_frame.pack(fill=tk.X, padx=5, pady=5)
        mode_frame = self.mode_frame
        self.mode_var = tk.StringVar(value='single')
        ttk.Radiobutton(mode_frame, text="Tek Kaydirici (Tension)",
                       variable=self.mode_var, value='single',
                       command=self.on_mode_change).pack(anchor=tk.W, padx=5, pady=2)
        ttk.Radiobutton(mode_frame, text="Cift Kaydirici (Softness + Snap)",
                       variable=self.mode_var, value='dual',
                       command=self.on_mode_change).pack(anchor=tk.W, padx=5, pady=2)

        # Tek kaydirici alani
        self.single_frame = ttk.LabelFrame(parent, text="Tek Kaydirici Modu")
        self.single_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(self.single_frame, text="Tension (Gerginlik)").pack(anchor=tk.W, padx=5, pady=(5, 0))
        self.tension_var = tk.DoubleVar(value=0.5)
        self.tension_scale = ttk.Scale(self.single_frame, from_=0, to=1,
                                       variable=self.tension_var, orient=tk.HORIZONTAL)
        self.tension_scale.pack(fill=tk.X, padx=5)
        self.tension_value_label = ttk.Label(self.single_frame, text="0.50")
        self.tension_value_label.pack(anchor=tk.W)
        self.tension_scale.configure(command=self._update_tension_label)
        ttk.Label(self.single_frame, text="0 = yumusak gecisler, 1 = siki palet",
                  foreground='#666').pack(anchor=tk.W, padx=5, pady=(0, 5))

        # Cift kaydirici alani
        self.dual_frame = ttk.LabelFrame(parent, text="Cift Kaydirici Modu")
        self.dual_frame.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(self.dual_frame, text="Softness (Etki Genisligi)").pack(anchor=tk.W, padx=5, pady=(5, 0))
        self.softness_var = tk.DoubleVar(value=0.5)
        self.softness_scale = ttk.Scale(self.dual_frame, from_=0, to=1,
                                        variable=self.softness_var, orient=tk.HORIZONTAL)
        self.softness_scale.pack(fill=tk.X, padx=5)

        ttk.Label(self.dual_frame, text="Snap (Palet Yapismasi)").pack(anchor=tk.W, padx=5, pady=(10, 0))
        self.snap_var = tk.DoubleVar(value=0.0)
        self.snap_scale = ttk.Scale(self.dual_frame, from_=0, to=1,
                                    variable=self.snap_var, orient=tk.HORIZONTAL)
        self.snap_scale.pack(fill=tk.X, padx=5)
        ttk.Label(self.dual_frame, text="0 = yapismasiz, 1 = tam palet yapismasi",
                  foreground='#666').pack(anchor=tk.W, padx=5, pady=(0, 5))

        # Etki gucu (her zaman gorunur)
        str_frame = ttk.LabelFrame(parent, text="Etki Gucu (tum modlarda)")
        str_frame.pack(fill=tk.X, padx=5, pady=5)
        ttk.Label(str_frame, text="Strength (Opaklik)").pack(anchor=tk.W, padx=5, pady=(5, 0))
        self.strength_var = tk.DoubleVar(value=1.0)
        self.strength_scale = ttk.Scale(str_frame, from_=0, to=1,
                                        variable=self.strength_var, orient=tk.HORIZONTAL)
        self.strength_scale.pack(fill=tk.X, padx=5)
        ttk.Label(str_frame, text="0 = orijinal, 1 = tam donusum",
                  foreground='#666').pack(anchor=tk.W, padx=5, pady=(0, 5))

        # Bilgi kutusu
        info_frame = ttk.LabelFrame(parent, text="Nasil Kullanilir?")
        info_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        info_text = (
            "1. Goruntu Yukle'ye bas.\n"
            "2. Gorsele tikla (kaynak renk secer).\n"
            "3. Paletten bir renge tikla (hedef).\n"
            "4. Birkac nokta icin tekrarla.\n"
            "5. Ayarlar'dan gerginligi vs. ayarla.\n"
            "6. Onizle'ye bas.\n"
            "7. Begenirsen Sonucu Kaydet'e bas."
        )
        ttk.Label(info_frame, text=info_text, justify=tk.LEFT).pack(anchor=tk.W, padx=5, pady=5)

        self.on_mode_change()

    def _update_tension_label(self, _=None):
        self.tension_value_label.config(text=f"{self.tension_var.get():.2f}")

    def on_mode_change(self):
        if self.mode_var.get() == 'single':
            self.dual_frame.pack_forget()
            self.single_frame.pack(fill=tk.X, padx=5, pady=5, after=self.mode_frame)
        else:
            self.single_frame.pack_forget()
            self.dual_frame.pack(fill=tk.X, padx=5, pady=5, after=self.mode_frame)

    # ============================================================
    # GORUNTU YUKLEME VE GORUNTULEME
    # ============================================================

    def load_image(self):
        path = filedialog.askopenfilename(
            title="Goruntu sec",
            filetypes=[
                ("Goruntu dosyalari", "*.jpg *.jpeg *.png *.bmp *.tiff *.webp"),
                ("Tum dosyalar", "*.*"),
            ]
        )
        if not path:
            return
        try:
            img = Image.open(path).convert('RGB')
            self.original_image = img
            self.image_array = np.array(img)
            self.showing_preview = False
            self.preview_array = None
            self._display_image(img)
            self.status_var.set(f"Yuklendi: {Path(path).name}  "
                                f"({img.width}x{img.height})")
        except Exception as e:
            messagebox.showerror("Hata", f"Goruntu yuklenemedi:\n{e}")

    def _display_image(self, pil_image):
        # Goruntuyu canvas boyutuna olcekle
        canvas_w = self.canvas.winfo_width() or 800
        canvas_h = self.canvas.winfo_height() or 600
        if canvas_w < 100 or canvas_h < 100:
            canvas_w, canvas_h = 800, 600

        w, h = pil_image.size
        scale = min(canvas_w / w, canvas_h / h, 1.0)  # asla buyultme
        self.scale_factor = scale
        new_w, new_h = int(w * scale), int(h * scale)

        resized = pil_image.resize((new_w, new_h), Image.LANCZOS)
        self.display_photo = ImageTk.PhotoImage(resized)

        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.display_photo)
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def show_original(self):
        if self.original_image is None:
            messagebox.showwarning("Uyari", "Once bir goruntu yukleyin.")
            return
        self.showing_preview = False
        self._display_image(self.original_image)
        self.status_var.set("Orijinal gosteriliyor.")

    # ============================================================
    # DAMLALIK - KAYNAK RENK SECME
    # ============================================================

    def on_canvas_click(self, event):
        if self.image_array is None:
            return
        # Goruntuleme koordinatlarini orijinal koordinatlara cevir
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        orig_x = int(canvas_x / self.scale_factor)
        orig_y = int(canvas_y / self.scale_factor)

        # Sinir kontrolu
        H, W = self.image_array.shape[:2]
        if not (0 <= orig_x < W and 0 <= orig_y < H):
            return

        # Piksel rengini al
        pixel = self.image_array[orig_y, orig_x]
        self.picked_source = (int(pixel[0]), int(pixel[1]), int(pixel[2]))

        # UI guncelle
        hex_color = '#%02x%02x%02x' % self.picked_source
        self.source_color_label.config(bg=hex_color)
        self.source_rgb_var.set(
            f"RGB: {self.picked_source}\n"
            f"Konum: ({orig_x}, {orig_y})"
        )
        self.status_var.set(f"Kaynak secildi: {self.picked_source}. "
                            f"Simdi paletten hedef renge tiklayin.")

    def on_canvas_motion(self, event):
        if self.image_array is None:
            return
        canvas_x = self.canvas.canvasx(event.x)
        canvas_y = self.canvas.canvasy(event.y)
        orig_x = int(canvas_x / self.scale_factor)
        orig_y = int(canvas_y / self.scale_factor)
        H, W = self.image_array.shape[:2]
        if not (0 <= orig_x < W and 0 <= orig_y < H):
            return
        pixel = self.image_array[orig_y, orig_x]
        rgb = (int(pixel[0]), int(pixel[1]), int(pixel[2]))
        hex_color = '#%02x%02x%02x' % rgb
        self.hover_label.config(text=f"RGB{rgb}", bg=hex_color,
                                fg='white' if sum(rgb) < 384 else 'black')

    def clear_source(self):
        self.picked_source = None
        self.source_color_label.config(bg='#808080')
        self.source_rgb_var.set("Henutz secilmedi")

    # ============================================================
    # PALET YONETIMI
    # ============================================================

    def _setup_default_palette(self):
        """Baslangic icin birkaç temel renk iceren ornek palet."""
        default = [
            (0, 0, 0),         # siyah
            (64, 64, 64),      # koyu gri
            (128, 128, 128),   # orta gri
            (192, 192, 192),   # acik gri
            (255, 255, 255),   # beyaz
            (255, 0, 0),       # kirmizi
            (255, 128, 0),     # turuncu
            (255, 255, 0),     # sari
            (128, 255, 0),     # lime
            (0, 255, 0),       # yesil
            (0, 255, 128),     # acik yesil-mavi
            (0, 255, 255),     # cyan
            (0, 128, 255),     # acik mavi
            (0, 0, 255),       # mavi
            (128, 0, 255),     # mor
            (255, 0, 255),     # magenta
            (255, 0, 128),     # pembe
            (128, 64, 0),      # kahverengi
            (200, 160, 120),   # ten rengi
            (255, 220, 180),   # acik ten
        ]
        for color in default:
            self.palette.append(color)
        self._render_palette()

    def _render_palette(self):
        # Eski swatch'leri temizle
        for sw in self.palette_swatches:
            sw.destroy()
        self.palette_swatches.clear()

        # Yeni swatch'leri grid olarak yerlestir
        cols = 4
        for i, color in enumerate(self.palette):
            r, c = divmod(i, cols)
            hex_color = '#%02x%02x%02x' % color
            sw = tk.Label(self.palette_inner, bg=hex_color, width=8, height=3,
                          relief=tk.RAISED, borderwidth=2, cursor='hand2')
            sw.grid(row=r, column=c, padx=2, pady=2, sticky='nsew')
            # Sol tik = hedef sec (eslesmeye ekle)
            sw.bind('<Button-1>', lambda e, c=color: self.on_palette_click(c))
            # Sag tik = rengin degerini goster
            sw.bind('<Button-3>', lambda e, c=color: self._show_color_info(c))
            self.palette_swatches.append(sw)

        # Grid sutunlarini esit genislik yap
        for c in range(cols):
            self.palette_inner.columnconfigure(c, weight=1)

        self.palette_info_var.set(f"{len(self.palette)} renk")

    def on_palette_click(self, color):
        # Kaynak secili mi kontrol et
        if self.picked_source is None:
            messagebox.showinfo("Bilgi",
                "Once goruntuye tiklayarak bir kaynak renk secin,\n"
                "sonra paletten hedef renge tiklayin.")
            return
        # Eslesmeye ekle
        mapping = {"src": self.picked_source, "dst": color}
        self.mappings.append(mapping)
        self._refresh_mappings_list()
        self.clear_source()
        self.status_var.set(f"Eslesme eklendi. Toplam: {len(self.mappings)} nokta.")

    def _show_color_info(self, color):
        messagebox.showinfo("Renk Bilgisi", f"RGB: {color}\nHEX: #%02x%02x%02x" % color)

    def add_color_manual(self):
        # RGB degerlerini kullanicidan al
        dlg = tk.Toplevel(self.root)
        dlg.title("Renk Ekle")
        dlg.geometry("300x200")
        dlg.transient(self.root)

        ttk.Label(dlg, text="R (0-255):").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        r_entry = ttk.Entry(dlg, width=10)
        r_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(dlg, text="G (0-255):").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        g_entry = ttk.Entry(dlg, width=10)
        g_entry.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(dlg, text="B (0-255):").grid(row=2, column=0, padx=5, pady=5, sticky=tk.W)
        b_entry = ttk.Entry(dlg, width=10)
        b_entry.grid(row=2, column=1, padx=5, pady=5)

        preview_label = tk.Label(dlg, bg='#808080', width=10, height=3, relief=tk.SUNKEN)
        preview_label.grid(row=3, column=0, columnspan=2, pady=5)

        def update_preview(_=None):
            try:
                r = int(r_entry.get())
                g = int(g_entry.get())
                b = int(b_entry.get())
                if all(0 <= v <= 255 for v in (r, g, b)):
                    preview_label.config(bg='#%02x%02x%02x' % (r, g, b))
            except ValueError:
                pass

        for e in (r_entry, g_entry, b_entry):
            e.bind('<KeyRelease>', update_preview)

        def on_ok():
            try:
                r = int(r_entry.get())
                g = int(g_entry.get())
                b = int(b_entry.get())
                if not all(0 <= v <= 255 for v in (r, g, b)):
                    raise ValueError()
                self.palette.append((r, g, b))
                self._render_palette()
                dlg.destroy()
            except ValueError:
                messagebox.showerror("Hata", "0-255 arasi sayi girin.", parent=dlg)

        ttk.Button(dlg, text="Ekle", command=on_ok).grid(row=4, column=0, pady=5)
        ttk.Button(dlg, text="Iptal", command=dlg.destroy).grid(row=4, column=1, pady=5)

    def clear_palette(self):
        if messagebox.askyesno("Onay", "Paleti temizlemek istediginize emin misiniz?"):
            self.palette.clear()
            self._render_palette()

    def load_palette_gpl(self):
        path = filedialog.askopenfilename(
            title="Palet sec (.gpl)",
            filetypes=[("GIMP Palette", "*.gpl"), ("Tum dosyalar", "*.*")]
        )
        if not path:
            return
        try:
            colors = []
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('GIMP Palette') or line.startswith('Name:') \
                       or line.startswith('Columns:') or line.startswith('#'):
                        continue
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                            colors.append((r, g, b))
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
            title="Palet kaydet",
            defaultextension=".gpl",
            filetypes=[("GIMP Palette", "*.gpl")]
        )
        if not path:
            return
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write("GIMP Palette\n")
                f.write(f"Name: {Path(path).stem}\n")
                f.write(f"Columns: 4\n")
                f.write("#\n")
                for c in self.palette:
                    f.write(f"{c[0]:3d} {c[1]:3d} {c[2]:3d}\tUntitled\n")
            self.status_var.set(f"Palet kaydedildi: {path}")
        except Exception as e:
            messagebox.showerror("Hata", f"Palet kaydedilemedi:\n{e}")

    # ============================================================
    # ESLESME LISTESI YONETIMI
    # ============================================================

    def _refresh_mappings_list(self):
        self.mappings_tree.delete(*self.mappings_tree.get_children())
        for i, m in enumerate(self.mappings):
            src = m["src"]
            dst = m["dst"]
            src_str = f"({src[0]},{src[1]},{src[2]})"
            dst_str = f"({dst[0]},{dst[1]},{dst[2]})"
            self.mappings_tree.insert('', tk.END, iid=str(i), values=(src_str, "->", dst_str))

    def delete_mapping(self):
        sel = self.mappings_tree.selection()
        if not sel:
            messagebox.showinfo("Bilgi", "Silmek icin bir eslesme secin.")
            return
        for item_id in sel:
            idx = int(item_id)
            if 0 <= idx < len(self.mappings):
                del self.mappings[idx]
        self._refresh_mappings_list()
        self.status_var.set(f"Silindi. Toplam: {len(self.mappings)} nokta.")

    def clear_mappings(self):
        if messagebox.askyesno("Onay", "Tum eslesmeleri silmek istediginize emin misiniz?"):
            self.mappings.clear()
            self._refresh_mappings_list()

    def save_mappings(self):
        if not self.mappings:
            messagebox.showwarning("Uyari", "Kaydedilecek eslesme yok.")
            return
        path = filedialog.asksaveasfilename(
            title="Eslesmeleri kaydet",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")]
        )
        if not path:
            return
        data = {
            "points": [
                {"src": list(m["src"]), "dst": list(m["dst"])}
                for m in self.mappings
            ]
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        self.status_var.set(f"Eslesmeler kaydedildi: {path}")

    def load_mappings(self):
        path = filedialog.askopenfilename(
            title="Eslesme dosyasi sec",
            filetypes=[("JSON", "*.json"), ("Tum dosyalar", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            points = data.get('points', data) if isinstance(data, dict) else data
            self.mappings = []
            for p in points:
                self.mappings.append({
                    "src": tuple(p["src"]),
                    "dst": tuple(p["dst"]),
                })
            self._refresh_mappings_list()
            self.status_var.set(f"Eslesmeler yuklendi: {len(self.mappings)} nokta.")
        except Exception as e:
            messagebox.showerror("Hata", f"Yuklenemedi:\n{e}")

    # ============================================================
    # DONUSUM UYGULAMA (ONIZLEME + KAYDETME)
    # ============================================================

    def _build_warp(self):
        if not self.mappings:
            messagebox.showwarning("Uyari", "Hic eslesme yok. Once birkac nokta secin.")
            return None
        src_colors = [m["src"] for m in self.mappings]
        tgt_colors = [m["dst"] for m in self.mappings]
        mode = self.mode_var.get()
        try:
            warp = ColorWarp(
                source_colors=src_colors,
                target_colors=tgt_colors,
                mode=mode,
                tension=self.tension_var.get(),
                softness=self.softness_var.get(),
                snap=self.snap_var.get(),
            )
            return warp
        except Exception as e:
            messagebox.showerror("Hata", f"Donusum motoru olusturulamadi:\n{e}")
            return None

    def preview(self):
        if self.image_array is None:
            messagebox.showwarning("Uyari", "Once bir goruntu yukleyin.")
            return
        warp = self._build_warp()
        if warp is None:
            return
        try:
            self.status_var.set("Hesaplaniyor... (buyuk goruntulerde birkaç saniye surebilir)")
            self.root.update()
            result = warp.apply(self.image_array, strength=self.strength_var.get())
            self.preview_array = result
            self.showing_preview = True
            preview_pil = Image.fromarray(result)
            self._display_image(preview_pil)
            self.status_var.set(
                f"Onizleme gosteriliyor. "
                f"Sigma={warp.sigma:.1f}, nokta sayisi={len(self.mappings)}. "
                f"Sonucu begenirsen 'Sonucu Kaydet'e bas."
            )
        except Exception as e:
            messagebox.showerror("Hata", f"Donusum hatasi:\n{e}")

    def save_result(self):
        if self.image_array is None:
            messagebox.showwarning("Uyari", "Once bir goruntu yukleyin.")
            return
        # Onizleme yoksa once donusum yap
        if self.preview_array is None or not self.showing_preview:
            warp = self._build_warp()
            if warp is None:
                return
            try:
                self.status_var.set("Hesaplaniyor...")
                self.root.update()
                self.preview_array = warp.apply(self.image_array, strength=self.strength_var.get())
            except Exception as e:
                messagebox.showerror("Hata", f"Donusum hatasi:\n{e}")
                return

        path = filedialog.asksaveasfilename(
            title="Sonucu kaydet",
            defaultextension=".png",
            filetypes=[
                ("PNG", "*.png"),
                ("JPEG", "*.jpg"),
                ("TIFF", "*.tiff"),
            ]
        )
        if not path:
            return
        try:
            Image.fromarray(self.preview_array).save(path)
            self.status_var.set(f"Kaydedildi: {path}")
            messagebox.showinfo("Tamam", f"Sonuc kaydedildi:\n{path}")
        except Exception as e:
            messagebox.showerror("Hata", f"Kaydedilemedi:\n{e}")


# ============================================================
# GIRIS NOKTASI
# ============================================================

def main():
    root = tk.Tk()
    app = RecolorGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
