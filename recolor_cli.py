#!/usr/bin/env python3
"""
Recolor CLI - Komut satirindan renk donusumu uygulama

Kullanim ornegi:

  python3 recolor_cli.py \\
      --input foto.jpg \\
      --output sonuc.jpg \\
      --points eslesmeler.json \\
      --tension 0.5 \\
      --strength 1.0

Eslesmeler.json formati:
  {
    "points": [
      {"src": [245, 240, 220], "dst": [255, 255, 255]},
      {"src": [130, 125, 110], "dst": [128, 128, 128]},
      ...
    ]
  }

Mod secenekleri:
  --mode single  (varsayilan): tek slider (tension)
  --mode dual:                  cift slider (softness + snap)

Dual modda:
  --softness 0.5  (0=dar etki, 1=genis etki)
  --snap 0.0      (0=yapistirma yok, 1=tam palet yapismasi)
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Ayni klasordeki cekirdek modulu ice aktar
sys.path.insert(0, str(Path(__file__).parent))
from recolor_core import ColorWarp


def load_control_points(json_path):
    """JSON dosyasindan kontrol noktalarini yukler.

    Beklenen format:
      {
        "points": [
          {"src": [r,g,b], "dst": [r,g,b]},
          ...
        ]
      }
    veya alternatif:
      [
        {"src": [r,g,b], "dst": [r,g,b]},
        ...
      ]
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Esnek format destegi
    if isinstance(data, dict) and 'points' in data:
        points = data['points']
    elif isinstance(data, list):
        points = data
    else:
        raise ValueError(
            "Gecersiz JSON formati. Beklenen:\n"
            '  {"points": [{"src": [r,g,b], "dst": [r,g,b]}, ...]}\n'
            "veya\n"
            '  [{"src": [...], "dst": [...]}, ...]'
        )

    source_colors = []
    target_colors = []
    for i, p in enumerate(points):
        if 'src' not in p or 'dst' not in p:
            raise ValueError(f"{i}. noktada 'src' veya 'dst' eksik")
        src = list(p['src'])
        dst = list(p['dst'])
        if len(src) != 3 or len(dst) != 3:
            raise ValueError(
                f"{i}. noktada renk 3 degerli olmali (RGB). "
                f"src={src}, dst={dst}"
            )
        source_colors.append(tuple(src))
        target_colors.append(tuple(dst))

    return source_colors, target_colors


def save_sample_points_file(path):
    """Ornek bir eslesmeler.json dosyasi olusturur (kullaniciya referans)."""
    sample = {
        "points": [
            {"src": [245, 240, 220], "dst": [255, 255, 255], "note": "sararmis beyaz -> saf beyaz"},
            {"src": [130, 125, 110], "dst": [128, 128, 128], "note": "bozuk gri -> saf gri"},
            {"src": [15, 15, 25], "dst": [0, 0, 0], "note": "mavimsi siyah -> saf siyah"},
            {"src": [60, 130, 70], "dst": [50, 150, 50], "note": "soluk yesil -> canli yesil"},
        ]
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(sample, f, indent=2, ensure_ascii=False)
    print(f"Ornek dosya olusturuldu: {path}")
    print("Bu dosyayi duzenleyip --points parametresi ile kullanabilirsiniz.")


def main():
    parser = argparse.ArgumentParser(
        description='Recolor - Renk donusum araci (lastik tablo metodu)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
ORNEKLER:

  1) Basit kullanim:
    python3 recolor_cli.py -i foto.jpg -o sonuc.jpg -p eslesmeler.json

  2) Tension ayarli:
    python3 recolor_cli.py -i foto.jpg -o sonuc.jpg -p eslesmeler.json --tension 0.7

  3) Dual mod (softness + snap):
    python3 recolor_cli.py -i foto.jpg -o sonuc.jpg -p eslesmeler.json \\
        --mode dual --softness 0.6 --snap 0.3

  4) Yari etki (strength=0.5):
    python3 recolor_cli.py -i foto.jpg -o sonuc.jpg -p eslesmeler.json --strength 0.5

  5) Ornek points dosyasi olustur:
    python3 recolor_cli.py --sample points_ornek.json
        """
    )
    parser.add_argument('-i', '--input', help='Giris goruntu dosyasi (jpg/png)')
    parser.add_argument('-o', '--output', help='Cikis goruntu dosyasi')
    parser.add_argument('-p', '--points', help='Kontrol noktalari JSON dosyasi')

    parser.add_argument('--mode', choices=['single', 'dual'], default='single',
                        help="single=tek slider (tension), dual=cift slider (softness+snap)")
    parser.add_argument('--tension', type=float, default=0.5,
                        help='Tek slider modunda gerginlik (0=duset, 1=siki) [0-1]')
    parser.add_argument('--softness', type=float, default=0.5,
                        help='Cift slider modunda etki genisligi (0=dar, 1=genis) [0-1]')
    parser.add_argument('--snap', type=float, default=0.0,
                        help='Cift slider modunda palet yapismasi (0=yok, 1=tam) [0-1]')
    parser.add_argument('--strength', type=float, default=1.0,
                        help='Etki gucu - opaklik gibi (0=orijinal, 1=tam donusum) [0-1]')

    parser.add_argument('--sample', help='Ornek points JSON dosyasi olustur ve cik')

    args = parser.parse_args()

    # Ornek dosya olusturma modu
    if args.sample:
        save_sample_points_file(args.sample)
        return

    # Parametre kontrol
    if not args.input or not args.output or not args.points:
        parser.error('--input, --output ve --points parametreleri zorunlu')
        return

    # Dosya kontrol
    if not Path(args.input).exists():
        print(f"HATA: Giris dosyasi bulunamadi: {args.input}")
        sys.exit(1)
    if not Path(args.points).exists():
        print(f"HATA: Points dosyasi bulunamadi: {args.points}")
        sys.exit(1)

    # 1) Goruntuyu yukle
    print(f"Goruntu yukleniyor: {args.input}")
    img = Image.open(args.input).convert('RGB')
    img_array = np.array(img)
    print(f"  Boyut: {img_array.shape[1]}x{img_array.shape[0]} piksel")

    # 2) Kontrol noktalarini yukle
    print(f"Kontrol noktalari yukleniyor: {args.points}")
    src_colors, tgt_colors = load_control_points(args.points)
    print(f"  {len(src_colors)} nokta bulundu")

    # 3) Donusum motorunu olustur
    print("Donusum motoru olusturuluyor...")
    warp = ColorWarp(
        source_colors=src_colors,
        target_colors=tgt_colors,
        mode=args.mode,
        tension=args.tension,
        softness=args.softness,
        snap=args.snap,
    )
    print(f"  Mode: {args.mode}")
    if args.mode == 'single':
        print(f"  Tension: {args.tension:.2f}")
    else:
        print(f"  Softness: {args.softness:.2f}, Snap: {args.snap:.2f}")
    print(f"  Strength: {args.strength:.2f}")
    print(f"  Sigma (etki yaricapi): {warp.sigma:.2f}")

    # 4) Donusumu uygula
    print("Donusum uygulaniyor...")
    result = warp.apply(img_array, strength=args.strength)

    # 5) Ciktiyi kaydet
    print(f"Sonuc kaydediliyor: {args.output}")
    Image.fromarray(result).save(args.output)
    print("TAMAM.")
    print()
    print("Kontrol noktasi dogrulama (her kaynak -> hedef birebir gitmeli):")
    for src, tgt in zip(src_colors, tgt_colors):
        out = warp.transform_single_color(src)
        match = "OK" if all(abs(a - b) <= 3 for a, b in zip(out, tgt)) else "FARK"
        print(f"  {src} -> hedef {tgt}  |  sonuc {out}  [{match}]")


if __name__ == '__main__':
    main()
