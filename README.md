# recolor

A small desktop tool for manually recoloring photos with exact match points
for each color - built to give faded, differently-shot photos a consistent
look (as if they came from the same lab).

## How it works

1. Load an image, pick a source color on it (eyedropper).
2. Click a target color in the palette.
3. Repeat for a few points, then press **Onizle (Preview)**.
4. Save the result at full resolution, or process a whole folder.

Under the hood the matched colors are mapped in the CIE-LAB color space
with a least-squares affine fit plus a Gaussian RBF correction, so every
matched color lands exactly on its target while the rest of the image
bends smoothly along.

## Requirements

- Python 3.8+
- tkinter (usually bundled with Python)
- Linux optional: `zenity` for native file dialogs (falls back to tkinter)

```bash
pip install -r requirements.txt
```

## Run

```bash
# GUI
python3 recolor_gui.py

# Command line
python3 recolor_cli.py -i photo.jpg -o result.jpg -p eslesmeler.json
python3 recolor_cli.py --sample points_ornek.json   # example points file
```

CLI options: `--softness` (effect width, 0=sharp/narrow, 1=soft/wide),
`--snap` (palette snapping, 0=off, 1=full), `--strength` (effect opacity,
0=original, 1=full conversion).

## Folders

- `input/`    copies of loaded files (session copies are cleaned on exit)
- `output/`   processed results
- `palettes/` GIMP (.gpl) palette files

## License

See the repository settings on GitHub.
