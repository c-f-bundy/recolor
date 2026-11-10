#!/usr/bin/env python3
"""
Recolor Core - Renk donusumunun matematiksel cekirdegi (v0.4.0)

Yontem (kullanicinin "lastik tablo" tarifi):
  1) Kaynak ve hedef renkler evrensel LAB renk uzayina cevrilir.
  2) Eslesen renkler en kucuk karelerle dogrusal (afin) bir esleme ile
     ust uste getirilir (3x3 matris + kaydirma).
  3) Kalan sapmalar Gauss RBF (yumuşak bükme) ile duzeltilir;
     eslesen renkler yine TAM hedefine gider.
  4) Snap: eslesen renklerin hedef rengine ne kadar "yapisacagi".

v0.4.0:
  - Tek kaydirici modu (tension) TAMAMEN kaldirildi. Iki ayar var:
    softness (RBF genisligi) ve snap (yapisma). Strength apply()'da.
  - Tam cozunurlukte apply() ARTIK PARCA PARCA (tile) calisir:
    dev ara diziler olusmaz, RAM kullanimi sabit kalir.
    Sonuc piksel piksel aynidir (tek parca hesapla birebir es).
"""

import warnings
warnings.filterwarnings('ignore', category=UserWarning)

import numpy as np
from skimage import color as skcolor

# Tek seferde islenecek azami piksel sayisi (RAM sigortasi).
# 400.000 piksel x 10 nokta x 3 kanal x 8 bayt ~ 96 MB ara dizi demektir.
CHUNK_PIXELS = 400_000


def rgb_to_lab(rgb_array):
    rgb_normalized = np.asarray(rgb_array, dtype=np.float64) / 255.0
    lab = skcolor.rgb2lab(rgb_normalized)
    return lab


def lab_to_rgb(lab_array):
    rgb_normalized = skcolor.lab2rgb(lab_array)
    rgb = rgb_normalized * 255.0
    rgb = np.clip(rgb, 0, 255)
    return rgb


class ColorWarp:
    """LAB uzayinda afin esleme + Gauss RBF duzeltme donusumu.

    Parametreler:
      source_colors / target_colors : eslesen RGB renk listeleri
      softness : 0..1  RBF etki genisligi (0=dar/net, 1=yumusak/genis)
      snap     : 0..1  eslesen renklerin hedefe yapismasi (0=yok, 1=tam)
    """

    def __init__(self, source_colors, target_colors, softness=0.5, snap=0.0):
        if len(source_colors) != len(target_colors):
            raise ValueError("Kaynak ve hedef renk sayisi esit olmali")
        if len(source_colors) < 1:
            raise ValueError("En az 1 kontrol noktasi gerekli")

        self.softness = float(np.clip(softness, 0.0, 1.0))
        self.snap = float(np.clip(snap, 0.0, 1.0))
        self.n_points = len(source_colors)

        src_rgb = np.array(source_colors, dtype=np.float64)
        tgt_rgb = np.array(target_colors, dtype=np.float64)
        self.src_lab = rgb_to_lab(src_rgb)
        self.tgt_lab = rgb_to_lab(tgt_rgb)

        self._fit_affine()
        affine_pred = (self.src_lab @ self.A.T) + self.b
        self.residuals = self.tgt_lab - affine_pred
        self._compute_sigma()
        self._fit_rbf()

    def _fit_affine(self):
        N = self.n_points
        S = self.src_lab
        T = self.tgt_lab
        ones = np.ones((N, 1))
        S_aug = np.hstack([S, ones])
        solution, _, _, _ = np.linalg.lstsq(S_aug, T, rcond=None)
        self.A = solution[:3].T
        self.b = solution[3]

    def _compute_sigma(self):
        if self.n_points >= 2:
            diffs = self.src_lab[:, None, :] - self.src_lab[None, :, :]
            dists = np.linalg.norm(diffs, axis=-1)
            mask = ~np.eye(self.n_points, dtype=bool)
            mean_dist = dists[mask].mean() if mask.sum() > 0 else 30.0
            mean_dist = max(mean_dist, 5.0)
        else:
            mean_dist = 30.0

        # v0.4.0: tek formul. tension ve gizli snap kaldirildi.
        scale = 0.3 + 1.7 * self.softness
        self.sigma = max(mean_dist * scale, 1.0)

    def _fit_rbf(self):
        diffs = self.src_lab[:, None, :] - self.src_lab[None, :, :]
        dists_sq = np.sum(diffs ** 2, axis=-1)
        self.Phi = np.exp(-dists_sq / (2.0 * self.sigma ** 2))
        self.W = np.linalg.solve(self.Phi, self.residuals)

    def apply(self, image_rgb, strength=1.0):
        """Donusumu goruntuye uygular. Buyuk goruntuler satir bloklari
        (tile) halinde islenir; sonuc tek parca hesapla birebir aynidir."""
        strength = float(np.clip(strength, 0.0, 1.0))
        if strength == 0.0:
            return np.asarray(image_rgb, dtype=np.uint8).copy()

        img = np.asarray(image_rgb, dtype=np.float64)
        H, W = img.shape[:2]

        rows_per_chunk = max(1, CHUNK_PIXELS // max(W, 1))
        out = np.empty_like(img)

        for y0 in range(0, H, rows_per_chunk):
            y1 = min(H, y0 + rows_per_chunk)
            chunk = img[y0:y1]
            lab = rgb_to_lab(chunk)
            lab_flat = lab.reshape(-1, 3)
            transformed_flat = self._transform_points(lab_flat)
            self._apply_snap(transformed_flat, lab_flat)
            rgb_flat = lab_to_rgb(transformed_flat)

            if strength < 1.0:
                orig_flat = chunk.reshape(-1, 3)
                rgb_flat = orig_flat * (1.0 - strength) + rgb_flat * strength

            out[y0:y1] = rgb_flat.reshape(y1 - y0, W, 3)

        return np.clip(out, 0, 255).astype(np.uint8)

    def _transform_points(self, lab_points):
        affine_part = lab_points @ self.A.T + self.b
        diffs = lab_points[:, None, :] - self.src_lab[None, :, :]
        dists_sq = np.sum(diffs ** 2, axis=-1)
        phi = np.exp(-dists_sq / (2.0 * self.sigma ** 2))
        rbf_part = phi @ self.W
        return affine_part + rbf_part

    def _apply_snap(self, transformed_lab, original_lab):
        # v0.4.0: snap artik dogrudan parametre; tension'dan gizli snap YOK.
        snap_level = self.snap
        if snap_level <= 0.001:
            return

        diffs = transformed_lab[:, None, :] - self.tgt_lab[None, :, :]
        dists = np.linalg.norm(diffs, axis=-1)
        nearest_idx = np.argmin(dists, axis=1)
        nearest_targets = self.tgt_lab[nearest_idx]

        np.add(
            transformed_lab * (1.0 - snap_level),
            nearest_targets * snap_level,
            out=transformed_lab,
        )

    def transform_single_color(self, rgb):
        arr = np.array([[rgb]], dtype=np.float64)
        result = self.apply(arr, strength=1.0)
        return tuple(int(v) for v in result[0, 0])


if __name__ == '__main__':
    print("Recolor Core v0.4.0 yuklendi. Self-test atlandi.")
