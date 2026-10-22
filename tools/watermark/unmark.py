"""Remove a visible watermark from pictures by masking it and filling the gap.

You say where the watermark is (a box, a mask image, or its colour); the script
finds the watermark pixels there, then either inpaints them from the
surrounding picture (photos) or paints them the page colour (scanned pages).

  python unmark.py in.jpg --box 820,600,300,80
  python unmark.py scans/ --box 0,0,1240,120 --doc --out cleaned/
  python unmark.py in.png --color 200,200,200 --tol 30 --preview
  python unmark.py in.png --mask mask.png
"""
import argparse, os, sys
import cv2
import numpy as np

EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff')


def parse_box(s):
    x, y, w, h = (int(v) for v in s.split(','))
    return x, y, w, h


def parse_rgb(s):
    r, g, b = (int(v) for v in s.split(','))
    return np.array([b, g, r], dtype=np.int16)  # OpenCV is BGR


def box_mask(img, boxes, polarity, thresh, whole, stroke):
    """Inside each box, mark pixels that stand out from the local background."""
    H, W = img.shape[:2]
    mask = np.zeros((H, W), np.uint8)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for x, y, w, h in boxes:
        x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if x1 <= x0 or y1 <= y0:
            continue
        if whole:
            mask[y0:y1, x0:x1] = 255
            continue
        # Top-hat: a grey-level opening (closing) with a kernel wider than the
        # watermark strokes erases light (dark) strokes completely, however
        # densely packed, while keeping the picture's broad shading.
        pad = stroke
        px0, py0, px1, py1 = max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad)
        roi = gray[py0:py1, px0:px1]
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (stroke | 1,) * 2)
        light = cv2.morphologyEx(roi, cv2.MORPH_TOPHAT, k)
        dark = cv2.morphologyEx(roi, cv2.MORPH_BLACKHAT, k)
        if polarity == 'light':
            hit = light > thresh
        elif polarity == 'dark':
            hit = dark > thresh
        else:
            hit = np.maximum(light, dark) > thresh
        sub = hit[y0 - py0:y1 - py0, x0 - px0:x1 - px0]
        mask[y0:y1, x0:x1][sub] = 255
    return mask


def color_mask(img, rgb, tol, boxes):
    dist = np.abs(img.astype(np.int16) - rgb).max(axis=2)
    mask = np.where(dist <= tol, 255, 0).astype(np.uint8)
    if boxes:  # limit the colour match to the given boxes
        keep = np.zeros_like(mask)
        for x, y, w, h in boxes:
            keep[max(0, y):y + h, max(0, x):x + w] = 255
        mask &= keep
    return mask


def page_colour(img):
    """Most common bright colour = the paper."""
    flat = img.reshape(-1, 3)
    bright = flat[flat.mean(axis=1) > 180]
    if len(bright) == 0:
        return np.array([255, 255, 255], np.uint8)
    return np.median(bright, axis=0).astype(np.uint8)


def clean(img, mask, args):
    if args.despeckle:
        # Drop specks thinner than N px, e.g. anti-aliased edges of real text
        # that happen to share the watermark's colour.
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (args.despeckle,) * 2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)
    if args.grow:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * args.grow + 1,) * 2)
        mask = cv2.dilate(mask, k)
    if args.doc:
        out = img.copy()
        # Keep real text: a watermark pixel darker than --keep-dark is assumed
        # to be ink printed over (or under) the watermark.
        lum = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        paint = (mask > 0) & (lum > args.keep_dark)
        out[paint] = page_colour(img)
        return out, mask
    method = cv2.INPAINT_NS if args.method == 'ns' else cv2.INPAINT_TELEA
    return cv2.inpaint(img, mask, args.radius, method), mask


def inputs(paths):
    for p in paths:
        if os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                if f.lower().endswith(EXTS):
                    yield os.path.join(p, f)
        else:
            yield p


def out_path(src, out_dir, suffix):
    base, ext = os.path.splitext(os.path.basename(src))
    folder = out_dir or os.path.dirname(src)
    return os.path.join(folder, base + suffix + ext)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('images', nargs='+', help='image files or folders')
    ap.add_argument('--box', action='append', type=parse_box, default=[],
                    help='x,y,w,h of the watermark area (repeatable)')
    ap.add_argument('--mask', help='mask image: white = watermark (same size as each input)')
    ap.add_argument('--color', type=parse_rgb, help='watermark colour R,G,B')
    ap.add_argument('--tol', type=int, default=25, help='colour tolerance for --color (default 25)')
    ap.add_argument('--polarity', choices=['light', 'dark', 'both'], default='both',
                    help='inside --box: is the watermark lighter or darker than the picture (default both)')
    ap.add_argument('--thresh', type=int, default=18,
                    help='inside --box: brightness difference that counts as watermark (default 18)')
    ap.add_argument('--stroke', type=int, default=31,
                    help='inside --box: px wider than the thickest watermark stroke (default 31)')
    ap.add_argument('--whole-box', action='store_true', help='treat every pixel in --box as watermark')
    ap.add_argument('--despeckle', type=int, default=3,
                    help='drop mask specks thinner than N px before growing; 0 = off (default 3)')
    ap.add_argument('--grow', type=int, default=2, help='grow the mask by N px to catch soft edges (default 2)')
    ap.add_argument('--method', choices=['telea', 'ns'], default='telea', help='inpainting method')
    ap.add_argument('--radius', type=int, default=5, help='inpainting radius (default 5)')
    ap.add_argument('--doc', action='store_true',
                    help='scanned page: paint watermark pixels the paper colour instead of inpainting')
    ap.add_argument('--keep-dark', type=int, default=110,
                    help='with --doc: never repaint pixels darker than this, i.e. text (default 110)')
    ap.add_argument('--out', help='output folder (default: next to each input)')
    ap.add_argument('--suffix', default='_clean', help='output name suffix (default _clean)')
    ap.add_argument('--preview', action='store_true', help='also save <name>_mask.png showing what was removed')
    args = ap.parse_args(argv)

    if not (args.box or args.mask or args.color is not None):
        ap.error('say where the watermark is: --box, --mask or --color')
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    fixed_mask = None
    if args.mask:
        fixed_mask = cv2.imread(args.mask, cv2.IMREAD_GRAYSCALE)
        if fixed_mask is None:
            ap.error(f'cannot read mask {args.mask}')
        fixed_mask = np.where(fixed_mask > 127, 255, 0).astype(np.uint8)

    done = 0
    for src in inputs(args.images):
        img = cv2.imread(src, cv2.IMREAD_COLOR)
        if img is None:
            print(f'skip {src}: not an image', file=sys.stderr)
            continue
        H, W = img.shape[:2]
        mask = np.zeros((H, W), np.uint8)
        if fixed_mask is not None:
            if fixed_mask.shape != (H, W):
                print(f'skip {src}: mask is {fixed_mask.shape[1]}x{fixed_mask.shape[0]}, image is {W}x{H}', file=sys.stderr)
                continue
            mask |= fixed_mask
        if args.color is not None:
            mask |= color_mask(img, args.color, args.tol, args.box)
        elif args.box:
            mask |= box_mask(img, args.box, args.polarity, args.thresh, args.whole_box, args.stroke)

        out, used = clean(img, mask, args)
        dst = out_path(src, args.out, args.suffix)
        cv2.imwrite(dst, out)
        pct = 100.0 * np.count_nonzero(used) / used.size
        print(f'{src} -> {dst}  ({pct:.2f}% of pixels replaced)')
        if args.preview:
            overlay = img.copy()
            overlay[used > 0] = (0, 0, 255)
            cv2.imwrite(out_path(src, args.out, '_mask').rsplit('.', 1)[0] + '.png',
                        cv2.addWeighted(img, 0.4, overlay, 0.6, 0))
        done += 1
    if not done:
        sys.exit('no images processed')


if __name__ == '__main__':
    main()
