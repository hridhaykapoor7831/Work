"""Find and remove one known watermark across a whole batch of pictures.

1. learn: show it the watermark once (a box on one picture). More pictures
   with the same mark sharpen the template; it is saved under templates/.

     python batch.py learn --name magicbricks --box 116,274,88,20 a.jpg b.jpg c.jpg

2. clean: give it a folder or a Drive .zip download. For every picture it
   looks for the watermark around the learned spot, removes it, and writes:
     <out>/clean/...         cleaned pictures, same names
     <out>/clean.zip         the same, zipped
     <out>/report.csv        per picture: found / assumed / skipped, score, place
     <out>/review.jpg        before/after strip of every watermark area

     python batch.py clean photos.zip --template templates/magicbricks --out result/

Faint marks on white or busy areas (beds, trees) score low. Those pictures are
cleaned at the place and size the confidently found ones in the same batch
used, and are marked "assumed" in the report so you can check them.
"""
import argparse, csv, json, os, shutil, sys, tempfile, zipfile
import cv2
import numpy as np

EXTS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')
HERE = os.path.dirname(os.path.abspath(__file__))


def tophat(img, stroke, polarity):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (stroke | 1,) * 2)
    op = cv2.MORPH_TOPHAT if polarity == 'light' else cv2.MORPH_BLACKHAT
    return cv2.morphologyEx(g, op, k).astype(np.float32)


def parse_box(s):
    return tuple(int(v) for v in s.split(','))


# ---------------------------------------------------------------- learn

def learn(args):
    imgs = [cv2.imread(p) for p in args.images]
    if any(i is None for i in imgs):
        sys.exit('cannot read one of the pictures')
    x, y, w, h = args.box
    H0, W0 = imgs[0].shape[:2]
    T = [tophat(i, args.stroke, args.polarity) for i in imgs]
    tpl = T[0][y:y + h, x:x + w].copy()
    # Re-find the mark in every example and average: backgrounds differ from
    # picture to picture, so they wash out and the letters remain.
    for _ in range(2):
        crops = []
        for t in T:
            r = cv2.matchTemplate(t, tpl, cv2.TM_CCOEFF_NORMED)
            _, sc, _, (lx, ly) = cv2.minMaxLoc(r)
            if sc >= 0.4 or t is T[0]:
                crops.append(t[ly:ly + h, lx:lx + w])
        tpl = np.mean(crops, axis=0)
    os.makedirs(os.path.dirname(args.name) or '.', exist_ok=True)
    cv2.imwrite(args.name + '.png', np.clip(tpl * 255.0 / tpl.max(), 0, 255).astype(np.uint8))
    meta = {'ref_width': W0, 'anchor': [(x + w / 2) / W0, (y + h / 2) / H0],
            'stroke': args.stroke, 'polarity': args.polarity, 'examples': len(crops)}
    json.dump(meta, open(args.name + '.json', 'w'), indent=1)
    print(f'template {args.name}.png from {len(crops)} pictures, {w}x{h} px, anchor {meta["anchor"]}')


# ---------------------------------------------------------------- clean

def load_template(base):
    tpl = cv2.imread(base + '.png', cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        sys.exit(f'no template at {base}.png (run learn first)')
    return tpl.astype(np.float32), json.load(open(base + '.json'))


def letter_mask(tpl):
    """The watermark's own shape: template pixels clearly above its noise."""
    t = cv2.GaussianBlur(tpl, (3, 3), 0).astype(np.uint8)
    _, m = cv2.threshold(t, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return m


def scaled(tpl, s):
    h, w = tpl.shape
    return cv2.resize(tpl, (max(4, round(w * s)), max(4, round(h * s))), interpolation=cv2.INTER_AREA)


def score_at(t, tp, cx, cy, reach):
    """Best match of template tp with its centre within reach px of (cx, cy)."""
    th, tw = tp.shape
    H, W = t.shape
    x0, y0 = int(round(cx - tw / 2)) - reach, int(round(cy - th / 2)) - reach
    x1, y1 = x0 + tw + 2 * reach, y0 + th + 2 * reach
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
        return -1.0, 0, 0
    r = cv2.matchTemplate(t[y0:y1, x0:x1], tp, cv2.TM_CCOEFF_NORMED)
    _, sc, _, (lx, ly) = cv2.minMaxLoc(r)
    return float(sc), lx - reach, ly - reach


def locate(img, tpl, meta, args):
    H, W = img.shape[:2]
    t = tophat(img, meta['stroke'], meta['polarity'])
    base = W / meta['ref_width']
    cx, cy = meta['anchor'][0] * W, meta['anchor'][1] * H
    best = (-1.0, 1.0, 0, 0)
    for m in np.arange(args.min_scale, args.max_scale + 1e-9, 0.05):
        sc, dx, dy = score_at(t, scaled(tpl, base * m), cx, cy, args.reach)
        if sc > best[0]:
            best = (sc, float(m), dx, dy)
    return t, best


def background(gray, x0, y0, w, h, stroke, pad=8):
    """The picture under the mark: a grey opening wipes out light strokes."""
    H, W = gray.shape
    ya, xa = max(0, y0 - pad), max(0, x0 - pad)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (stroke | 1,) * 2)
    bg = cv2.morphologyEx(gray[ya:min(H, y0 + h + pad), xa:min(W, x0 + w + pad)], cv2.MORPH_OPEN, k)
    return bg[y0 - ya:y0 - ya + h, x0 - xa:x0 - xa + w].astype(np.float32)


def busy(img, x0, y0, w, h, stroke):
    """Lines or texture under the mark (inpainting smears them), or a near-white
    area (where reversing the overlay is exact). Either way, unblend."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    bg = background(gray, x0, y0, w, h, stroke)
    grad = np.hypot(cv2.Sobel(bg, cv2.CV_32F, 1, 0), cv2.Sobel(bg, cv2.CV_32F, 0, 1))
    return np.percentile(grad, 90) > 100 or bg.mean() > 215


def unblend(img, alpha_shape, x0, y0, stroke, kmax):
    """Undo a translucent white overlay: I = (1-a)J + 255a, with a = k * shape.
    k is fitted per picture; the placement is refined by +-1 px."""
    H, W = img.shape[:2]
    h, w = alpha_shape.shape
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    best = None
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            xs, ys = x0 + dx, y0 + dy
            if xs < 0 or ys < 0 or xs + w > W or ys + h > H:
                continue
            bg = background(gray.astype(np.uint8), xs, ys, w, h, stroke)
            d = gray[ys:ys + h, xs:xs + w] - bg
            a = alpha_shape * (255 - bg)
            k = max(0.0, float((d * a).sum() / max((a * a).sum(), 1e-6)))
            res = float(((d - k * a) ** 2).sum())
            if best is None or res < best[0]:
                best = (res, k, xs, ys)
    if best is None:
        return img, 0.0
    _, k, xs, ys = best
    k = min(k, kmax)
    al = (k * alpha_shape)[..., None]
    out = img.copy()
    roi = img[ys:ys + h, xs:xs + w].astype(np.float32)
    out[ys:ys + h, xs:xs + w] = np.clip((roi - al * 255) / (1 - al), 0, 255).astype(np.uint8)
    return out, k


def place(tpl, s, cx, cy, dx, dy):
    tp = scaled(tpl, s)
    th, tw = tp.shape
    return tp, int(round(cx - tw / 2)) + dx, int(round(cy - th / 2)) + dy


def inpaint(img, mask, tp, x0, y0, args):
    H, W = img.shape[:2]
    ms = cv2.resize(mask, tp.shape[::-1], interpolation=cv2.INTER_NEAREST)
    th, tw = ms.shape
    full = np.zeros((H, W), np.uint8)
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x0 + tw), min(H, y0 + th)
    full[ya:yb, xa:xb] = ms[ya - y0:yb - y0, xa - x0:xb - x0]
    if args.grow:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * args.grow + 1,) * 2)
        full = cv2.dilate(full, k)
    return cv2.inpaint(img, full, args.radius, cv2.INPAINT_TELEA)


def remove(img, tpl, mask, meta, s, cx, cy, dx, dy, kmax, args):
    """Returns cleaned picture, (x, y, x2, y2) of the mark, method used."""
    H, W = img.shape[:2]
    tp, x0, y0 = place(tpl, s, cx, cy, dx, dy)
    th, tw = tp.shape
    box = (max(0, x0), max(0, y0), min(W, x0 + tw), min(H, y0 + th))
    inside = x0 >= 0 and y0 >= 0 and x0 + tw <= W and y0 + th <= H
    method = args.method
    if method == 'auto':
        method = 'unblend' if inside and busy(img, x0, y0, tw, th, meta['stroke']) else 'inpaint'
    if method == 'unblend' and inside:
        shape = tp / 255.0
        shape[shape < 0.25] = 0  # template noise outside the letters
        out, k = unblend(img, shape, x0, y0, meta['stroke'], kmax)
        return out, box, f'unblend k={k:.2f}'
    return inpaint(img, mask, tp, x0, y0, args), box, 'inpaint'


def gather(src, tmp):
    """Pictures from a folder or a .zip (zip entries are flattened to their names)."""
    if os.path.isdir(src):
        return [os.path.join(src, f) for f in sorted(os.listdir(src)) if f.lower().endswith(EXTS)]
    if zipfile.is_zipfile(src):
        out = []
        with zipfile.ZipFile(src) as z:
            for n in sorted(z.namelist()):
                name = os.path.basename(n)
                if not name or not name.lower().endswith(EXTS):
                    continue
                dst = os.path.join(tmp, name)
                with z.open(n) as a, open(dst, 'wb') as b:
                    shutil.copyfileobj(a, b)
                out.append(dst)
        return out
    return [src]


def clean(args):
    tpl, meta = load_template(args.template)
    mask = letter_mask(tpl)
    tmp = tempfile.mkdtemp()
    files = []
    for s in args.inputs:
        files += gather(s, tmp)
    if not files:
        sys.exit('no pictures found')
    out_dir = os.path.join(args.out, 'clean')
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    for f in files:
        img = cv2.imread(f)
        if img is None:
            rows.append({'file': os.path.basename(f), 'status': 'unreadable'})
            continue
        _, (sc, m, dx, dy) = locate(img, tpl, meta, args)
        rows.append({'file': os.path.basename(f), 'path': f, 'img': img, 'score': sc,
                     'scale': m, 'dx': dx, 'dy': dy,
                     'status': 'found' if sc >= args.min_score else None})

    # Low scorers take the placement the confident ones used, preferring
    # pictures of the same size, then the closest shape.
    sure = [r for r in rows if r.get('status') == 'found']
    for r in rows:
        if r.get('status') is not None or 'img' not in r:
            continue
        if not sure or args.no_assume:
            r['status'] = 'skipped'
            continue
        H, W = r['img'].shape[:2]
        ref = min(sure, key=lambda q: (q['img'].shape[:2] != (H, W),
                                       abs(q['img'].shape[0] / q['img'].shape[1] - H / W)))
        r.update(scale=ref['scale'], dx=ref['dx'], dy=ref['dy'], status='assumed', like=ref['file'])

    # Confident pictures first: their overlay strengths cap how strong a mark
    # the "assumed" ones may be given (busy textures can fake a strong fit).
    strips = []
    kmax = 0.6
    for r in sorted((r for r in rows if 'img' in r), key=lambda r: r['status'] != 'found'):
        img = r['img']
        H, W = img.shape[:2]
        cx, cy = meta['anchor'][0] * W, meta['anchor'][1] * H
        dst = os.path.join(out_dir, r['file'])
        if r['status'] == 'skipped':
            cv2.imwrite(dst, img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            continue
        if r['status'] == 'assumed':
            ks = [float(q['method'].split('=')[1]) for q in rows if q.get('method', '').startswith('unblend')]
            kmax = max(ks) if ks else 0.4
        s = W / meta['ref_width'] * r['scale']
        out, (xa, ya, xb, yb), r['method'] = remove(img, tpl, mask, meta, s, cx, cy, r['dx'], r['dy'], kmax, args)
        cv2.imwrite(dst, out, [cv2.IMWRITE_JPEG_QUALITY, 95])
        r['box'] = f'{xa},{ya},{xb - xa},{yb - ya}'
        pad = 12
        y0, y1, x0, x1 = max(0, ya - pad), min(H, yb + pad), max(0, xa - pad), min(W, xb + pad)
        strips.append((r, img[y0:y1, x0:x1], out[y0:y1, x0:x1]))

    with open(os.path.join(args.out, 'report.csv'), 'w', newline='') as fh:
        wr = csv.writer(fh)
        wr.writerow(['file', 'status', 'score', 'scale', 'box', 'method', 'placed_like'])
        for r in rows:
            wr.writerow([r['file'], r['status'], f"{r.get('score', 0):.2f}", f"{r.get('scale', 0):.2f}",
                         r.get('box', ''), r.get('method', ''), r.get('like', '')])

    if strips:
        strips.sort(key=lambda t: t[0]['file'])
        write_review(strips, os.path.join(args.out, 'review.jpg'))
    zpath = os.path.join(args.out, 'clean.zip')
    with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_DEFLATED) as z:
        for r in rows:
            if 'img' in r:
                z.write(os.path.join(out_dir, r['file']), r['file'])
    shutil.rmtree(tmp, ignore_errors=True)

    for r in rows:
        extra = f"  (placed like {r['like']})" if r.get('like') else ''
        print(f"{r['status']:8s} {r.get('score', 0):5.2f}  {r.get('method', ''):14s} {r['file']}{extra}")
    n = {k: sum(r['status'] == k for r in rows) for k in ('found', 'assumed', 'skipped', 'unreadable')}
    print(f"\n{n['found']} found, {n['assumed']} assumed, {n['skipped']} skipped, "
          f"{n['unreadable']} unreadable -> {out_dir}, {zpath}")


def write_review(strips, path, zoom=3):
    rows = []
    for r, a, b in strips:
        a = cv2.resize(a, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
        b = cv2.resize(b, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
        gap = np.full((a.shape[0], 10, 3), 255, np.uint8)
        label = np.full((34, a.shape[1] * 2 + 10, 3), 255, np.uint8)
        colour = (0, 120, 0) if r['status'] == 'found' else (0, 110, 230)
        cv2.putText(label, f"{r['file']}  {r['status']} {r['score']:.2f}  {r['method']}", (6, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2)
        rows.append(np.vstack([label, np.hstack([a, gap, b])]))
    w = max(x.shape[1] for x in rows)
    rows = [np.pad(x, ((0, 8), (0, w - x.shape[1]), (0, 0)), constant_values=255) for x in rows]
    cv2.imwrite(path, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 90])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)

    a = sub.add_parser('learn', help='make a template from example pictures')
    a.add_argument('images', nargs='+', help='pictures with the watermark; the first one is where --box is')
    a.add_argument('--box', type=parse_box, required=True, help='x,y,w,h around the watermark in the first picture')
    a.add_argument('--name', required=True, help='template name or path, e.g. templates/magicbricks')
    a.add_argument('--stroke', type=int, default=7, help='px wider than the watermark strokes (default 7)')
    a.add_argument('--polarity', choices=['light', 'dark'], default='light', help='watermark lighter or darker (default light)')

    c = sub.add_parser('clean', help='remove the watermark from a folder or zip of pictures')
    c.add_argument('inputs', nargs='+', help='folders, .zip files or pictures')
    c.add_argument('--template', required=True, help='template name or path given to learn')
    c.add_argument('--out', default='unmarked', help='output folder (default unmarked/)')
    c.add_argument('--min-score', type=float, default=0.33, help='match score that counts as found (default 0.33)')
    c.add_argument('--min-scale', type=float, default=0.7, help='smallest size to try vs. the template (default 0.7)')
    c.add_argument('--max-scale', type=float, default=1.3, help='largest size to try (default 1.3)')
    c.add_argument('--reach', type=int, default=6, help='px the mark may sit away from the learned spot (default 6)')
    c.add_argument('--no-assume', action='store_true', help='leave low-scoring pictures untouched instead')
    c.add_argument('--method', choices=['auto', 'inpaint', 'unblend'], default='auto',
                   help='inpaint (rebuild from surroundings), unblend (reverse the translucent overlay), '
                        'or auto: unblend over lines, texture or white areas, else inpaint (default)')
    c.add_argument('--grow', type=int, default=1, help='grow the letter mask by N px (default 1)')
    c.add_argument('--radius', type=int, default=3, help='inpainting radius (default 3)')

    args = ap.parse_args(argv)
    if args.cmd == 'learn':
        learn(args)
    else:
        if not os.path.dirname(args.template) and not os.path.exists(args.template + '.png'):
            args.template = os.path.join(HERE, 'templates', args.template)
        clean(args)


if __name__ == '__main__':
    main()
