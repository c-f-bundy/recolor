# Recolor

**Recolor old photos with GIMP palettes — exact, repeatable color mapping. Built for LoRA training datasets.**

![License](https://img.shields.io/badge/License-AGPL--3.0-blue)
![Python](https://img.shields.io/badge/Python-3.9%2B-blue)
![GUI](https://img.shields.io/badge/GUI-Tkinter-informational)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey)

---

## Why?

Old photos rarely have *wrong* colors — they have *shifted* colors: yellowed whites, bluish blacks, faded greens. Fixing them one by one in a general editor is slow, and every photo ends up slightly different.

Recolor takes the opposite approach. You define a handful of **match points** — "this dirty gray becomes this clean gray" — and the engine stretches the *entire* color space around those points, like a rubber sheet. Every photo processed with the same points gets **exactly the same treatment** — which is what a training dataset needs most: consistency.

- **Exact** — every source color lands precisely on its target. After each CLI run the tool verifies and prints this for every point.
- **Smooth** — no hard thresholds; colors between your points move gently and stay plausible.

## How it works

1. Source and target colors are converted to the CIE-LAB color space.
2. A least-squares affine map pulls all pairs together.
3. The remaining deviation is corrected with a smooth Gaussian RBF (the "rubber sheet") — matched colors still land exactly on their targets.
4. Large images are processed in tiles, so RAM usage stays constant regardless of size.

## Features

- **GUI** — dark theme, zoom, full-resolution live preview, RGB sliders, grid view
- **Match points** — pick a source color from the photo (or set it with the RGB sliders), then click a palette color as its target
- **GIMP palettes** — load/save `.gpl` files, or build a palette from an image
- **Batch mode** — apply the same points to a whole folder
- **CLI** — same engine for scripted pipelines
- **Only three knobs** — `softness`, `snap`, `strength`
- **Constant memory** — huge images are processed in tiles
- **Native dialogs** — Linux file dialogs (zenity) that open in the right folder

## Installation

Requires **Python 3.9+** (tkinter comes bundled with Python on Linux).

    # 1. Get the code
    git clone https://github.com/c-f-bundy/recolor.git
    cd recolor
    # (or download and unzip the latest release)

    # 2. Install dependencies
    pip install -r requirements.txt

    # 3. Run the GUI
    python3 recolor_gui.py

Notes:
- `zenity` is optional and only used for the native file dialogs on Linux (preinstalled on most distros).
- Keep your `.gpl` palettes in the `palettes/` folder next to the scripts.

## Quick start (GUI)

1. Run `python3 recolor_gui.py`.
2. Open a photo — or a whole folder for batch work.
3. Click a color in the photo, or set one with the RGB sliders: that's your **source**.
4. Click a color in the palette: that's its **target**. Repeat for a few key colors.
5. Check the live preview, adjust if needed.
6. Save — or run the batch over the folder.

Keyboard shortcuts (single image view):

| Key | Action |
| --- | --- |
| Left / Right arrow | previous / next photo |
| mouse wheel | zoom |
| Ctrl + wheel | vertical scrolling |
| Shift + wheel | horizontal scrolling |
| double-click | back to grid view |

## Command line

    # basic
    python3 recolor_cli.py -i foto.jpg -o sonuc.jpg -p eslesmeler.json

    # softer, wider effect
    python3 recolor_cli.py -i foto.jpg -o sonuc.jpg -p eslesmeler.json --softness 0.8

    # colors snap harder onto their targets
    python3 recolor_cli.py -i foto.jpg -o sonuc.jpg -p eslesmeler.json --snap 0.4

    # half-strength result, like an opacity slider
    python3 recolor_cli.py -i foto.jpg -o sonuc.jpg -p eslesmeler.json --strength 0.5

    # create a template points file to edit
    python3 recolor_cli.py --sample points_ornek.json

| Option | Meaning | Range (default) |
| --- | --- | --- |
| `--softness` | Width of the effect: 0 = sharp and narrow, 1 = soft and wide | 0–1 (0.5) |
| `--snap` | How strongly matched colors stick to their exact targets | 0–1 (0.0) |
| `--strength` | Overall strength of the transformation | 0–1 (1.0) |

## The points file

A points file is plain JSON — `src` is the color you have, `dst` is the color it must become, `note` is for you. The repo ships a working example: **`eslesmeler_ornek.json`**.

    {
      "points": [
        { "src": [245, 240, 220], "dst": [255, 255, 255], "note": "yellowed white -> pure white" },
        { "src": [130, 125, 110], "dst": [128, 128, 128], "note": "off gray -> pure gray" },
        { "src": [15, 15, 25],    "dst": [0, 0, 0],       "note": "bluish black -> pure black" },
        { "src": [60, 130, 70],   "dst": [50, 150, 50],   "note": "faded green -> vivid green" }
      ]
    }

A bare list without the `"points"` wrapper is accepted too. Generate an empty template with `python3 recolor_cli.py --sample points_ornek.json`.

## Folders

| Folder | Purpose |
| --- | --- |
| `input/` | copies of the photos you open |
| `output/` | processed results |
| `palettes/` | your `.gpl` palette files |

## Version history

| Version | Highlights |
| --- | --- |
| [v0.1.0](https://github.com/c-f-bundy/recolor/releases/tag/v0.1.0) | Core color engine — LAB rubber-sheet mapping with exact match points |
| [v0.2.0](https://github.com/c-f-bundy/recolor/releases/tag/v0.2.0) | Modern GUI — dark theme, zoom, live preview, RGB sliders |
| [v0.3.0](https://github.com/c-f-bundy/recolor/releases/tag/v0.3.0) | Batch processing, grid view, native dialogs, bigger fonts |
| [v0.4.0](https://github.com/c-f-bundy/recolor/releases/tag/v0.4.0) | Panel layout fixes, dialogs open in the right working folder |

## License

This project is licensed under the **GNU Affero General Public License v3.0** — see [LICENSE](LICENSE).

- Anyone may use, study, modify and share Recolor, as long as derived works stay open under the same license — including when the software is offered as a network service.
- **Your photos stay yours.** The license covers the program code only; Recolor claims no rights over the images you process with it. Use the output anywhere — commercially included.
