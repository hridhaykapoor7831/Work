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
- **Small, thin watermark text** (1–2 px strokes, e.g. on a phone-sized listing photo): `--despeckle 0 --stroke 7 --grow 1 --radius 3`. The default despeckle would erase the mask itself.
- **Watermark crosses a thin bright edge** (a sill or frame line): the edge gets caught in the mask and comes out softened. Raise `--thresh` until the preview mostly shows only the letters.

Results go to `<name>_clean.<ext>` next to the input, or into `--out`.

## Limits

- Inpainting rebuilds small and thin areas well. A large opaque logo over detailed content (faces, text) will look smeared, because that information is gone.
- Use it on pictures you own or have the right to edit. Stock and copyrighted watermarks are there to protect someone else's licence.

# batch.py: the batch system (one known watermark, many pictures)

Use this when many pictures carry the same mark, for example every photo in a listing.

**1. Learn the watermark once.** Draw a box around it on one picture. Adding more pictures with the mark sharpens the template, because their different backgrounds average out.

```
python batch.py learn --name templates/magicbricks --box 116,274,88,20 a.jpg b.jpg c.jpg d.jpg
```

`templates/magicbricks.png` and `.json` are already learned from four listing photos (320 px wide, mark at the centre).

**2. Clean a folder or a Drive `.zip` download.**

```
python batch.py clean photos.zip --template magicbricks --out result/
```

This writes:

- `result/clean/`: the cleaned pictures, same file names
- `result/clean.zip`: the same, zipped for re-upload
- `result/report.csv`: one row per picture, with its status, score, placement and method
- `result/review.jpg`: a zoomed before/after strip of every watermark area, to check at a glance

**How it decides.** It searches near the learned spot (±6 px, 0.7–1.3× size) and gives each picture one of three statuses:

| Status | Meaning |
|---|---|
| **found** | The match score is at least 0.33. |
| **assumed** | The mark is too faint to confirm, which happens on white beds, busy furniture and trees. The picture is cleaned at the place and size used by the closest-shaped picture that was found. Check these in `review.jpg`. Pass `--no-assume` to leave them untouched instead. |
| **skipped** | Nothing in the batch was found, so it has no placement to borrow. |

**Two removal methods.** `--method auto`, the default, picks one per picture:

- **inpaint** rebuilds the letters from the surrounding picture. It works best on plain floors and walls, but it smears lines that cross the mark, like skirting boards, bed edges and sills.
- **unblend** reverses the translucent white overlay using the learned letter shape, so anything underneath survives. It can leave a faint ghost of the letters. It's used when the area has lines or texture, or is near-white.

To force one method, pass `--method inpaint` or `--method unblend`. Run it on the whole batch: a picture run on its own has no found pictures to borrow a placement from, so an "assumed" one would be skipped.
