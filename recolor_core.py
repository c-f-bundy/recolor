"""
Recolor Core - Renk dönüştürme matematiksel çekirdeği

Bu modül "lastik tablo" mantığını uygular:
  - Kullanıcı bazı renkleri başka renklere eşler (kontrol noktaları)
  - Program bir dönüşüm fonksiyonu inşa eder
  - Bu fonksiyon fotoğraftaki tüm piksellere uygulanır

Kullanıcının kontrol ettiği 3 ayar:
  1. Eslestirme noktalari (damlalik + palet)
  2. Etki gucu (strength): donusumun ne kadar uygulandigi (0-1, opaklik gibi)
  3. Gerginlik (tension):
     - 0: yumusak gecisler, palet disi renkler az etkilenir
     - 1: palet disi renkler palet renklerine yapisir

Iki mod var:
  - Tek slider modu: tension = tek kaydirici
  - Cift slider modu: softness (etki genisligi) + snap (palet yapismasi)
"""

import numpy as np
from skimage import color as skcolor


# ============================================================
# 1. RENK UZAYI DONUSUMLERI (RGB <-> LAB)
# ============================================================
# LAB kullaniyoruz cunku insan gozunun algilayisina yakin.
# Parlaklik (L) ve renk (a, b) ayri kanallarda -> daha dogal sonuclar.

def rgb_to_lab(rgb_array):
    """RGB degerlerini LAB'a cevirir.

    Parametre:
      rgb_array: (..., 3) boyutlu array, 0-255 arasi RGB degerleri
    Donus:
      Ayni boyutta LAB degerleri (L: 0-100, a: ~-128..127, b: ~-128..127)
    """
    # 0-255 -> 0-1 (skimage bunu bekler)
    rgb_normalized = np.asarray(rgb_array, dtype=np.float64) / 255.0
    lab = skcolor.rgb2lab(rgb_normalized)
    return lab


def lab_to_rgb(lab_array):
    """LAB degerlerini RGB'ye cevirir, gamut kontrolu yapar.

    Parametre:
      lab_array: (..., 3) boyutlu LAB degerleri
    Donus:
      Ayni boyutta, 0-255 arasi kistirilmis RGB degerleri (uint8 degil, float)
    """
    rgb_normalized = skcolor.lab2rgb(lab_array)
    # 0-1 -> 0-255
    rgb = rgb_normalized * 255.0
    # Gamut kontrolu: 0-255 disina cikanlari kistira
    rgb = np.clip(rgb, 0, 255)
    return rgb


# ============================================================
# 2. COLOR WARP SINIFI (Lastik tablo motoru)
# ============================================================

class ColorWarp:
    """Renk donusum motoru.

    Kullanim:
      warp = ColorWarp(
          source_colors=[(255,255,255), (200,180,100), ...],
          target_colors=[(240,240,235), (180,140,90), ...],
          mode='single',         # 'single' veya 'dual'
          tension=0.5,           # tek slider modunda 0-1
          softness=0.5,          # cift slider modunda 0-1 (etki genisligi)
          snap=0.0,              # cift slider modunda 0-1 (palet yapismasi)
      )
      result_image = warp.apply(image_rgb, strength=1.0)
    """

    def __init__(
        self,
        source_colors,
        target_colors,
        mode='single',
        tension=0.5,
        softness=0.5,
        snap=0.0,
    ):
        if len(source_colors) != len(target_colors):
            raise ValueError(
                f"Kaynak ve hedef renk sayisi esit olmali: "
                f"{len(source_colors)} vs {len(target_colors)}"
            )
        if len(source_colors) < 1:
            raise ValueError("En az 1 kontrol noktasi gerekli")

        # Parametreleri kaydet
        self.mode = mode
        self.tension = float(np.clip(tension, 0.0, 1.0))
        self.softness = float(np.clip(softness, 0.0, 1.0))
        self.snap = float(np.clip(snap, 0.0, 1.0))
        self.n_points = len(source_colors)

        # 1) Kontrol noktalarini LAB'a cevir
        src_rgb = np.array(source_colors, dtype=np.float64)  # (N, 3)
        tgt_rgb = np.array(target_colors, dtype=np.float64)  # (N, 3)
        self.src_lab = rgb_to_lab(src_rgb)  # (N, 3)
        self.tgt_lab = rgb_to_lab(tgt_rgb)  # (N, 3)

        # 2) Affine donusumu coz (genel trend)
        self._fit_affine()

        # 3) Residualleri hesapla
        affine_pred = (self.src_lab @ self.A.T) + self.b  # (N, 3)
        self.residuals = self.tgt_lab - affine_pred  # (N, 3)

        # 4) RBF kernel parametresi (sigma) hesapla
        self._compute_sigma()

        # 5) RBF agirliklarini coz
        self._fit_rbf()

    # -------------------- AFFINE --------------------
    def _fit_affine(self):
        """Affine donusumu least-squares ile cozer.

        f_affine(x) = A @ x + b
          A: 3x3 matris (genel olcekleme/dondurma)
          b: 3 vektor (oteleme)

        Cozum: [A | b] = (S^T S)^-1 S^T T  (normal denklemler)
        Burada S'ye '1' sutunu eklenir, boylece A ve b ayni anda cozulur.
        """
        N = self.n_points
        S = self.src_lab  # (N, 3)
        T = self.tgt_lab  # (N, 3)

        # S'ye '1' sutunu ekle -> (N, 4)
        ones = np.ones((N, 1))
        S_aug = np.hstack([S, ones])  # (N, 4)

        # Least-squares: S_aug @ [A^T; b^T] = T
        # Yani 4x3 bilinmeyen matris cozuyoruz
        solution, residuals, rank, sv = np.linalg.lstsq(S_aug, T, rcond=None)
        # solution: (4, 3) -> ilk 3 satir = A^T, son satir = b
        self.A = solution[:3].T  # (3, 3)
        self.b = solution[3]     # (3,)

    # -------------------- SIGMA --------------------
    def _compute_sigma(self):
        """RBF'nin etki yari capini (sigma) hesaplar.

        Mod'a gore farkli davranir:
          - single: tension yuksek oldukca sigma kuculur (dar etki)
          - dual:   softness yuksek oldukca sigma buyur (genis etki)
        """
        # Kontrol noktalari arasindaki ortalama mesafe
        if self.n_points >= 2:
            # Tum ciftlerin mesafeleri
            diffs = self.src_lab[:, None, :] - self.src_lab[None, :, :]  # (N, N, 3)
            dists = np.linalg.norm(diffs, axis=-1)  # (N, N)
            # Sifir kosegeni (kendine mesafe) haric tut
            mask = ~np.eye(self.n_points, dtype=bool)
            mean_dist = dists[mask].mean() if mask.sum() > 0 else 30.0
            # Cok kucukse minimum bir deger ver
            mean_dist = max(mean_dist, 5.0)
        else:
            mean_dist = 30.0  # Tek nokta varsa varsayilan

        if self.mode == 'single':
            # Tek slider: tension 0 -> sigma buyuk (yayvan)
            #             tension 1 -> sigma kucuk (dar)
            # sigma'yi tension'a gore 0.2x ile 2.0x arasi olcekleyelim
            scale = 2.0 - 1.8 * self.tension  # tension=0 -> 2.0, tension=1 -> 0.2
            self.sigma = mean_dist * scale
        else:
            # Cift slider: softness 0 -> dar, softness 1 -> genis
            scale = 0.3 + 1.7 * self.softness  # 0.3x ile 2.0x
            self.sigma = mean_dist * scale

        # Sigma sifir olmasin
        self.sigma = max(self.sigma, 1.0)

    # -------------------- RBF --------------------
    def _fit_rbf(self):
        """RBF agirliklarini cozer.

        Kernel matrisi Phi[i,j] = exp(-||src_i - src_j||^2 / (2*sigma^2))
        Cozulecek: Phi @ W = residuals  ->  W = Phi^-1 @ residuals
        """
        diffs = self.src_lab[:, None, :] - self.src_lab[None, :, :]  # (N, N, 3)
        dists_sq = np.sum(diffs ** 2, axis=-1)  # (N, N)
        self.Phi = np.exp(-dists_sq / (2.0 * self.sigma ** 2))  # (N, N)

        # Coz
        self.W = np.linalg.solve(self.Phi, self.residuals)  # (N, 3)

    # -------------------- APPLY --------------------
    def apply(self, image_rgb, strength=1.0):
        """Donusumu bir goruntuye uygular.

        Parametre:
          image_rgb: (H, W, 3) uint8 veya float array, 0-255 RGB
          strength: 0-1, donusumun ne kadar uygulanacagi (opaklik gibi)

        Donus:
          (H, W, 3) uint8 array, donusturulmus goruntu
        """
        strength = float(np.clip(strength, 0.0, 1.0))
        if strength == 0.0:
            return np.asarray(image_rgb, dtype=np.uint8).copy()

        # Goruntuyu hazirla
        img = np.asarray(image_rgb, dtype=np.float64)  # (H, W, 3)
        original_shape = img.shape
        H, W = original_shape[:2]

        # LAB'a cevir
        lab = rgb_to_lab(img)  # (H, W, 3)
        lab_flat = lab.reshape(-1, 3)  # (H*W, 3)

        # Donusumu uygula
        transformed_flat = self._transform_points(lab_flat)  # (H*W, 3)

        # Snap (palet yapismasi) uygula - sadece dual modda veya tension yuksekken
        self._apply_snap(transformed_flat, lab_flat)

        # LAB -> RGB
        rgb_flat = lab_to_rgb(transformed_flat)  # (H*W, 3)

        # Strength (opaklik) karisimi
        if strength < 1.0:
            orig_flat = img.reshape(-1, 3)
            rgb_flat = orig_flat * (1.0 - strength) + rgb_flat * strength

        # Ciktiyi bicimlendir
        result = rgb_flat.reshape(original_shape)
        return np.clip(result, 0, 255).astype(np.uint8)

    def _transform_points(self, lab_points):
        """LAB noktalarina (affine + RBF) donusumunu uygular.

        Parametre:
          lab_points: (M, 3) LAB noktalari
        Donus:
          (M, 3) donusturulmus LAB noktalari
        """
        M = lab_points.shape[0]

        # Affine kismi: A @ x + b
        affine_part = lab_points @ self.A.T + self.b  # (M, 3)

        # RBF kismi: her nokta icin sum_i W_i * phi(||x - src_i||)
        # Bu M x N matris islemi
        # distances: (M, N)
        diffs = lab_points[:, None, :] - self.src_lab[None, :, :]  # (M, N, 3)
        dists_sq = np.sum(diffs ** 2, axis=-1)  # (M, N)
        phi = np.exp(-dists_sq / (2.0 * self.sigma ** 2))  # (M, N)

        rbf_part = phi @ self.W  # (M, 3)

        return affine_part + rbf_part

    def _apply_snap(self, transformed_lab, original_lab):
        """Palet yapismasi (snap) uygular.

        Snap degeri yuksek oldukca, her piksel en yakin hedef palete yapisir.

        Parametreler:
          transformed_lab: (M, 3) donusturulmus LAB (in-place degistirilir)
          original_lab:    (M, 3) orijinal LAB (referans icin)
        """
        # Snap seviyesini belirle
        if self.mode == 'single':
            snap_level = max(0.0, (self.tension - 0.5) * 2.0)  # 0.5+ kisim snap
            snap_level = min(snap_level, 1.0)
        else:
            snap_level = self.snap

        if snap_level <= 0.001:
            return  # Snap yok

        # Her piksel icin en yakin hedef LAB rengini bul
        # Bu M x N matris islemi
        diffs = transformed_lab[:, None, :] - self.tgt_lab[None, :, :]  # (M, N, 3)
        dists = np.linalg.norm(diffs, axis=-1)  # (M, N)
        nearest_idx = np.argmin(dists, axis=1)  # (M,)
        nearest_targets = self.tgt_lab[nearest_idx]  # (M, 3)

        # Snap karisimi
        np.add(
            transformed_lab * (1.0 - snap_level),
            nearest_targets * snap_level,
            out=transformed_lab,
        )

    # -------------------- SINGLE COLOR TEST --------------------
    def transform_single_color(self, rgb):
        """Tek bir rengi donusturur (GUI'de hover/onizleme icin).

        Parametre:
          rgb: (r, g, b) tuple veya array, 0-255
        Donus:
          (r, g, b) tuple, 0-255
        """
        arr = np.array([[rgb]], dtype=np.float64)  # (1, 1, 3)
        result = self.apply(arr, strength=1.0)
        return tuple(int(v) for v in result[0, 0])


# ============================================================
# 3. TEST FONKSIYONU
# ============================================================

def self_test():
    """Cekirdek modulu test eder - sentetik goruntu ile."""

    # Sentetik test goruntusu: 6 renk bloku
    # Bunlar "bozuk" kaynak renkler - sararmis/bukuk
    test_image = np.zeros((200, 600, 3), dtype=np.uint8)
    # 1. Beyazimsi (sarimsi)
    test_image[:, 0:100] = (245, 240, 220)
    # 2. Gri (bozuk)
    test_image[:, 100:200] = (130, 125, 110)
    # 3. Siyah (biraz mavimsi)
    test_image[:, 200:300] = (15, 15, 25)
    # 4. Yesilimsi
    test_image[:, 300:400] = (60, 130, 70)
    # 5. Mavi (soluk)
    test_image[:, 400:500] = (90, 110, 180)
    # 6. Kahverengimsi
    test_image[:, 500:600] = (140, 100, 70)

    # Kontrol noktalari: kaynak -> hedef
    # Hedefler "temiz" bir palet
    source_colors = [
        (245, 240, 220),  # sararmis beyaz
        (130, 125, 110),  # bozuk gri
        (15, 15, 25),     # mavimsi siyah
        (60, 130, 70),    # soluk yesil
        (90, 110, 180),   # soluk mavi
        (140, 100, 70),   # kahverengimsi
    ]
    target_colors = [
        (255, 255, 255),  # saf beyaz
        (128, 128, 128),  # saf gri
        (0, 0, 0),        # saf siyah
        (50, 150, 50),    # canli yesil
        (60, 90, 200),    # canli mavi
        (120, 70, 40),    # derin kahve
    ]

    # 3 modu test et:
    # 1. Duset gerginlik (yumuşak)
    warp_lo = ColorWarp(source_colors, target_colors, mode='single', tension=0.2)
    result_lo = warp_lo.apply(test_image, strength=1.0)

    # 2. Yuksek gerginlik (siki - palet yapismasi)
    warp_hi = ColorWarp(source_colors, target_colors, mode='single', tension=0.9)
    result_hi = warp_hi.apply(test_image, strength=1.0)

    # 3. Yari etki (strength=0.5)
    result_half = warp_hi.apply(test_image, strength=0.5)

    # Goruntuleri kaydet
    from PIL import Image
    out_dir = '/home/z/my-project/download'

    Image.fromarray(test_image).save(f'{out_dir}/test_original.png')
    Image.fromarray(result_lo).save(f'{out_dir}/test_tension_low.png')
    Image.fromarray(result_hi).save(f'{out_dir}/test_tension_high.png')
    Image.fromarray(result_half).save(f'{out_dir}/test_strength_half.png')

    # Bilgi yazdir
    print("=" * 60)
    print("RECOLOR CORE - TEST SONUCLARI")
    print("=" * 60)
    print(f"Kontrol noktasi sayisi: {len(source_colors)}")
    print(f"Sigma (duset): {warp_lo.sigma:.2f}")
    print(f"Sigma (yuksek): {warp_hi.sigma:.2f}")
    print()
    print("Kaynak -> Hedef dogrulama (transform_single_color):")
    for src, tgt in zip(source_colors, target_colors):
        result = warp_hi.transform_single_color(src)
        match = "OK" if all(abs(a-b) <= 3 for a, b in zip(result, tgt)) else "FARK"
        print(f"  {src} -> {tgt}  |  sonuc: {result}  [{match}]")
    print()
    print("Ciktilar:")
    print(f"  {out_dir}/test_original.png        (orijinal)")
    print(f"  {out_dir}/test_tension_low.png     (duset gerginlik)")
    print(f"  {out_dir}/test_tension_high.png    (yuksek gerginlik)")
    print(f"  {out_dir}/test_strength_half.png   (yari etki)")
    print("=" * 60)


if __name__ == '__main__':
    self_test()
