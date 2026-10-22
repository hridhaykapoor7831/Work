# unmark.py: remove a visible watermark from pictures

Needs `pip install opencv-python-headless numpy`.

You tell it where the watermark is. It works out which pixels belong to the watermark there, then fills them in:

- **Photos** (default): the gap is inpainted from the surrounding picture (OpenCV Telea or Navier–Stokes).
- **Scanned pages** (`--doc`): watermark pixels are painted the paper colour. Pixels darker than `--keep-dark` (the printed text) are never touched.

## Telling it where the watermark is

| Option | Use when |
|---|---|
| `--box x,y,w,h` (repeatable) | The watermark sits in a known area. Inside the box, pixels lighter or darker than the local background count as watermark. Set `--polarity light` for white or translucent marks and `--polarity dark` for dark ones. |
| `--box ... --whole-box` | Replace the entire box, for example a solid logo badge. |
| `--color R,G,B --tol N` | The watermark has one flat colour, like the grey "CONFIDENTIAL" on scans. Add `--box` to limit the match to an area. |
| `--mask mask.png` | You painted the watermark white on black in any editor. The mask must be the same size as the image. |

## Examples

```
# translucent white logo in the bottom-right of a photo
python unmark.py photo.jpg --box 820,600,300,80 --polarity light --preview

# grey diagonal stamp across a folder of scans
python unmark.py scans/ --color 195,195,195 --tol 15 --doc --out cleaned/
```

`--preview` writes `<name>_mask.png` with the removed pixels shown in red. Check it, then tune the settings:

- **Watermark left behind:** raise `--grow` or `--tol`, or lower `--thresh`.
- **Real detail removed:** lower `--tol`, raise `--thresh` or `--despeckle`, or make the box tighter.
- **Thick watermark strokes not fully caught:** raise `--stroke` above the stroke width in px.

Results go to `<name>_clean.<ext>` next to the input, or into `--out`.

## Limits

- Inpainting rebuilds small and thin areas well. A large opaque logo over detailed content (faces, text) will look smeared, because that information is gone.
- Use it on pictures you own or have the right to edit. Stock and copyrighted watermarks are there to protect someone else's licence.
