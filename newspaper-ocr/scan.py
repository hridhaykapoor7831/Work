#!/usr/bin/env python3
"""Scan photographed newspaper pages (a PDF) for notices that mention target areas.

    python3 scan.py Oct_21.pdf            # writes Oct_21_scan/ next to the PDF
    python3 scan.py Oct_21.pdf -o out/    # choose the output folder
    python3 scan.py Oct_21.pdf --fast     # fewer OCR passes (quicker, lower recall)

Outputs:
    <name>_highlighted.pdf  pages turned upright, every hit boxed, searchable text layer
    <name>_report.html      one card per notice with a cropped picture and the matched words
    <name>_hits.csv         one row per hit
    <name>_ocr.txt          full OCR text, for Ctrl+F

What is matched is controlled by targets.json next to this script.
"""
import argparse
import base64
import csv
import html
import io
import json
import re
import sys
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import pymupdf as fitz
import numpy as np
import pytesseract
from PIL import Image, ImageDraw
from rapidfuzz.distance import Levenshtein

HERE = Path(__file__).resolve().parent
TIERS = ["HIGH", "MEDIUM", "REVIEW"]
VISION = "claude-vision"
TIER_RGB = {"HIGH": (0.86, 0.08, 0.08), "MEDIUM": (0.95, 0.5, 0.0), "REVIEW": (0.1, 0.45, 0.9)}
TIER_HEX = {"HIGH": "#d91414", "MEDIUM": "#f28000", "REVIEW": "#1a73e6"}
MAX_SIDE = 5000  # px; long side of the page image handed to OCR


# ---------------------------------------------------------------- data types

@dataclass
class Word:
    text: str
    conf: float
    box: tuple  # x0, y0, x1, y1 in upright-page pixels
    skel: str = ""


@dataclass
class Hit:
    page: int
    kind: str          # "name" or "pincode"
    term: str          # gazetteer name or the pincode
    area: str
    tier: str
    seen: str          # what OCR actually read
    box: tuple
    distance: int = 0
    note: str = ""
    passes: set = field(default_factory=set)
    context: str = ""
    region: tuple = None
    signatory: bool = False
    boxes: list = field(default_factory=list)  # one per word: a hit can wrap onto the next line


# ---------------------------------------------------------------- text normalisation

_CONFUSE = str.maketrans({"0": "o", "1": "l", "|": "l", "!": "l", "5": "s", "$": "s", "@": "a", "i": "l"})


def skel(s):
    """Lower-case letters-only form that folds common OCR confusions together."""
    s = re.sub(r"[^a-z0-9|!$@]", "", s.lower()).translate(_CONFUSE)
    return s.replace("rn", "m").replace("vv", "w")


_DIGITISE = str.maketrans({"O": "0", "o": "0", "Q": "0", "D": "0", "I": "1", "l": "1", "|": "1", "!": "1",
                           "S": "5", "s": "5", "B": "8", "Z": "2", "z": "2"})
_DIG = r"[0-9OoQDIl|!SsBZz]"
PIN_RE = re.compile(rf"(?<![0-9])(4\s?{_DIG}\s?{_DIG})\s?[-–—.]?\s?({_DIG}\s?{_DIG}\s?{_DIG})(?![0-9])")


# ---------------------------------------------------------------- targets

GENERIC_WORDS = {skel(w) for w in """road rd marg street st lane path building bldg house hall chambers chamber
tower towers centre center bhavan bhawan mahal nagar park cinema hotel college station police market bazar
estate circle chowk division club court stadium gallery terminus apartments mansion plaza dock pier the of
for and capt captain dr sir mumbai bombay west east no new old""".split()}

class Targets:
    def __init__(self, path):
        d = json.loads(Path(path).read_text())
        self.target_pins = d["pincodes"]["target"]
        self.border_pins = d["pincodes"]["border"]
        self.known_pins = d.get("known_pincodes_approx", {})
        generic = {g.lower() for g in d.get("generic_names", [])}
        self.cues = {c.lower() for c in d.get("signatory_cues", [])}
        self.terms = []
        exact_only = {e.lower() for e in d.get("exact_only", [])}
        for group in d["terms"]:
            for name in group["names"]:
                sk = skel(name)
                toks = name.split()
                # typo allowance is set by the distinctive part only, so "Road"/"Building" can't carry a match
                core = "".join(skel(t) for t in toks if skel(t) not in GENERIC_WORDS) or sk
                if any(len(t) == 1 for t in toks) or len(core) <= 5 or name.lower() in exact_only:
                    allowed = 0
                elif len(core) <= 8:
                    allowed = 1
                elif len(core) <= 14:
                    allowed = 2
                else:
                    allowed = 3
                loose = allowed + 1 if allowed and len(core) >= 9 else allowed
                self.terms.append(dict(name=name, area=group["area"], tier=group["tier"], skel=sk,
                                       ntok=len(toks), allowed=allowed, loose=loose,
                                       generic=name.lower() in generic))
        self.by_len = {}
        for t in self.terms:
            self.by_len.setdefault(len(t["skel"]), []).append(t)
        self.ignore = [skel(p) for p in d.get("ignore_phrases", [])]


# ---------------------------------------------------------------- page images

def page_images(pdf_path):
    doc = fitz.open(pdf_path)
    for page in doc:
        native = max((info[2] for info in page.get_images(full=True)), default=0)
        zoom = max(native / page.rect.width if native else 0, 300 / 72)
        zoom = min(zoom, MAX_SIDE / max(page.rect.width, page.rect.height))
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csRGB, alpha=False)
        yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def _normalise(gray):
    """Divide out uneven lighting (shadows, page curl) – the single biggest OCR gain on phone photos."""
    return cv2.divide(gray, cv2.GaussianBlur(gray, (0, 0), 31), scale=255)


def _quick_score(img):
    # psm 6 = one plain block with no layout analysis; psm 3 quietly re-orients sideways text
    # itself, which makes 90° and 180° score the same and hides the true orientation
    arr = _normalise(cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY))
    d = pytesseract.image_to_data(Image.fromarray(arr), config="--oem 1 --psm 6", output_type=pytesseract.Output.DICT)
    return sum(1 for c, t in zip(d["conf"], d["text"]) if len(t.strip()) >= 4 and float(c) > 80)


def upright(img):
    """Rotate the photo so text reads normally. Returns (image, degrees clockwise applied, method).

    Tesseract's orientation detector got a sideways test page wrong, so every page is read at all
    four rotations and the one producing the most confident words wins.
    """
    small = img.copy()
    small.thumbnail((2000, 2000))
    scores = {r: _quick_score(small.rotate(-r, expand=True)) for r in (0, 90, 180, 270)}
    rot = max(scores, key=scores.get)
    runner_up = sorted(scores.values())[-2]
    method = f"best of 4 rotations ({scores[rot]} confident words vs {runner_up})"
    return img.rotate(-rot, expand=True), rot, method


# ---------------------------------------------------------------- OCR passes

# Measured on phone photos of newsprint: no single preparation reads everything, but the union of
# these passes recovered 58 of 59 probe words across the test pages (best single pass: 49).
PASSES = [("norm", 1.0, 3), ("norm", 1.5, 3), ("norm", 2.0, 3), ("norm", 2.0, 4), ("norm", 2.0, 11),
          ("otsu", 2.0, 3), ("otsu", 2.0, 4)]
FAST_PASSES = [("norm", 1.0, 3), ("norm", 2.0, 3)]


def ocr_passes(img, fast=False):
    """Run several OCR passes on differently prepared copies; each pass returns blocks of Words.

    Boxes are always mapped back to the coordinates of `img` so passes can be merged.
    """
    gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
    norm = _normalise(gray)
    scaled = {}
    out = []
    for kind, scale, psm in (FAST_PASSES if fast else PASSES):
        if scale not in scaled:
            scaled[scale] = norm if scale == 1 else cv2.resize(norm, None, fx=scale, fy=scale,
                                                              interpolation=cv2.INTER_CUBIC)
        arr = scaled[scale]
        if kind == "otsu":
            arr = cv2.threshold(arr, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        out.append((f"{kind}x{scale:g}/psm{psm}", _ocr(arr, psm, scale=scale)))
    return out


def _ocr(arr, psm, scale=1.0):
    d = pytesseract.image_to_data(Image.fromarray(arr), config=f"--oem 1 --psm {psm} -c preserve_interword_spaces=1",
                                  output_type=pytesseract.Output.DICT)
    blocks = {}
    for i, text in enumerate(d["text"]):
        text = text.strip()
        if not text:
            continue
        x, y, w, h = (d[k][i] / scale for k in ("left", "top", "width", "height"))
        key = (d["block_num"][i], d["par_num"][i] if psm != 11 else 0)
        # "Street/Chakla" is two words to a reader; split so each can start or end a match
        parts = [p for p in re.split(r"(?<=[A-Za-z.,])/(?=[A-Za-z])", text) if p]
        cx = x
        for p in parts:
            pw = w * len(p) / max(1, sum(map(len, parts)))
            blocks.setdefault(key, []).append(Word(p, float(d["conf"][i]), (cx, y, cx + pw, y + h)))
            cx += pw
    return list(blocks.values())


# ---------------------------------------------------------------- matching

def _union(boxes):
    boxes = list(boxes)
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def _overlap(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if not inter:
        return 0.0
    small = min((a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1]))
    return inter / small if small else 0.0


def _demote(tier):
    return TIERS[min(TIERS.index(tier) + 1, 2)]


def _context(words, i, j, span=25):
    lo, hi = max(0, i - span), min(len(words), j + span)
    parts = []
    for k in range(lo, hi):
        t = html.escape(words[k].text)
        parts.append(f"<mark>{t}</mark>" if i <= k < j else t)
    return ("… " if lo else "") + " ".join(parts) + (" …" if hi < len(words) else "")


def _is_signatory(words, i, cues):
    before = [re.sub(r"[^a-z/-]", "", w.text.lower()) for w in words[max(0, i - 15):i]]
    return any(b in cues for b in before)


def match_block(words, page_no, pass_name, T, page_area):
    for w in words:
        w.skel = skel(w.text)
    hits = []

    # ignore phrases (e.g. "Advocate High Court") – mark their tokens off-limits
    banned = set()
    for ph in T.ignore:
        for i in range(len(words)):
            acc = ""
            for j in range(i, min(i + 6, len(words))):
                acc += words[j].skel
                if acc == ph:
                    banned.update(range(i, j + 1))
                if len(acc) >= len(ph):
                    break

    # names: sliding windows over tokens (handles line breaks and hyphenation inside a block)
    cands = []
    n_words = len(words)
    for i in range(n_words):
        if not words[i].skel:
            continue
        acc = ""
        for j in range(i, min(i + 7, n_words)):
            acc += words[j].skel
            L = len(acc)
            for tl in range(max(1, L - 4), L + 5):
                for t in T.by_len.get(tl, ()):
                    if not (t["ntok"] - 1 <= j - i + 1 <= t["ntok"] + 2):
                        continue
                    if abs(L - tl) > t["loose"]:
                        continue
                    d = Levenshtein.distance(acc, t["skel"], score_cutoff=t["loose"])
                    if d <= t["loose"]:
                        cands.append((d, i, j + 1, t))
            if L > 40:
                break
    # long names fused into neighbouring words ("Mumbai-CuffeParade")
    joined, owner = "", []
    for k, w in enumerate(words):
        joined += w.skel
        owner += [k] * len(w.skel)
    for t in T.terms:
        if len(t["skel"]) < 8:
            continue
        start = joined.find(t["skel"])
        while start >= 0:
            cands.append((0, owner[start], owner[start + len(t["skel"]) - 1] + 1, t))
            start = joined.find(t["skel"], start + 1)

    cands.sort(key=lambda c: (c[0] > 0, -len(c[3]["skel"]), c[0]))
    taken = set()
    for d, i, j, t in cands:
        span = set(range(i, j))
        if span & taken or span & banned:
            continue
        # a fuzzy hit that is just a different real word of similar shape is noise: require the
        # window to start at the same letter unless it is an exact skeleton match
        if d and words[i].skel[:1] != t["skel"][:1]:
            continue
        taken |= span
        if d == 0:
            tier, note = t["tier"], "exact"
        elif d <= t["allowed"]:
            tier, note = _demote(t["tier"]), f"fuzzy ({d} letter{'s' if d > 1 else ''} different)"
        else:
            tier, note = "REVIEW", f"loose fuzzy ({d} letters different)"
        if t["generic"] and d == 0 and tier == "HIGH":
            after = " ".join(w.skel for w in words[j:j + 8])
            pins_after = re.sub(r"\D", "", " ".join(w.text for w in words[j:j + 8]).translate(_DIGITISE))
            if not ("mumbal" in after or "bombay" in after or any(p in pins_after for p in T.target_pins)):
                tier, note = "MEDIUM", "exact, but a common word – no Mumbai/pincode right after"
        hits.append(Hit(page_no, "name", t["name"], t["area"], tier, " ".join(w.text for w in words[i:j]),
                        _union(w.box for w in words[i:j]), d, note, {pass_name},
                        _context(words, i, j), page_area(words), _is_signatory(words, i, T.cues),
                        [w.box for w in words[i:j]]))

    # pincodes
    text, starts = "", []
    for w in words:
        starts.append(len(text))
        text += w.text + " "
    for m in PIN_RE.finditer(text):
        raw = m.group(0)
        pin = re.sub(r"\D", "", raw.translate(_DIGITISE))
        if len(pin) != 6:
            continue
        i = max(k for k, s in enumerate(starts) if s <= m.start())
        j = max(k for k, s in enumerate(starts) if s < m.end()) + 1
        corrected = re.sub(r"[\s\-–—.]", "", raw) != pin
        note = "OCR-corrected digits" if corrected else ""
        if pin in T.target_pins:
            tier, area = "HIGH", T.target_pins[pin]
        elif pin in T.border_pins:
            tier, area, note = "REVIEW", "Border: " + T.border_pins[pin], (note + "; border pincode").strip("; ")
        else:
            close = [p for p in T.target_pins if sum(a != b for a, b in zip(p, pin)) == 1]
            if close and pin not in T.known_pins:
                tier, area = "REVIEW", f"not a known Mumbai pincode – possible misread of {'/'.join(close)}"
            else:
                tier, area = None, T.known_pins.get(pin, "")
        hits.append(Hit(page_no, "pincode", pin, area, tier, raw.strip(), _union(w.box for w in words[i:j]), 0,
                        note, {pass_name}, _context(words, i, j), page_area(words),
                        _is_signatory(words, i, T.cues), [w.box for w in words[i:j]]))
    return hits


def merge(hits):
    """Collapse the same hit found by several OCR passes; keep the best reading."""
    merged = []
    for h in sorted(hits, key=lambda h: (TIERS.index(h.tier) if h.tier else 3, h.distance)):
        for m in merged:
            same_words = any(_overlap(a, b) > 0.5 for a in m.boxes for b in h.boxes)
            claude_involved = VISION in m.passes | h.passes
            both_claude_only = m.passes == h.passes == {VISION}
            # different names on the same words = one reading won; but Claude's boxes are whole tiles,
            # so with Claude only the same name can merge (and its overlapping tiles count as one)
            same = m.term == h.term and (same_words or both_claude_only) or \
                (m.kind == "name" and same_words and not claude_involved)
            if m.page == h.page and m.kind == h.kind and same:
                if m.passes == {VISION} and VISION not in h.passes:
                    # Claude's hit only knows its tile; take the exact word boxes OCR found
                    m.box, m.boxes, m.region, m.seen = h.box, h.boxes, h.region, h.seen
                m.passes |= h.passes
                m.signatory = m.signatory or h.signatory
                break
        else:
            merged.append(h)
    return merged


def _notice_region(hit, blocks):
    """Smallest layout block holding the hit's centre; keeps the hit's own region if none does."""
    cx, cy = (hit.box[0] + hit.box[2]) / 2, (hit.box[1] + hit.box[3]) / 2
    inside = [b for b in blocks if b[0] <= cx <= b[2] and b[1] <= cy <= b[3]]
    return min(inside, key=lambda b: (b[2] - b[0]) * (b[3] - b[1])) if inside and hit.passes != {VISION} \
        else hit.region


def group_notices(hits):
    """Cluster flagged hits that sit in the same printed notice (overlapping regions)."""
    groups = []
    for h in sorted(hits, key=lambda h: (h.page, h.region[1], h.region[0])):
        for g in groups:
            if g[0].page == h.page and any(_overlap(x.region, h.region) > 0.6 or _overlap(x.region, h.box) > 0.9
                                           or _overlap(h.region, x.box) > 0.9 for x in g):
                g.append(h)
                break
        else:
            groups.append([h])
    groups.sort(key=lambda g: (min(TIERS.index(x.tier) for x in g), g[0].page))
    return groups


# ---------------------------------------------------------------- outputs

def _crop(img, region, hits, max_w=1400):
    x0, y0, x1, y1 = (int(v) for v in region)
    crop = img.crop((x0, y0, x1, y1)).convert("RGB")
    draw = ImageDraw.Draw(crop)
    for h in hits:
        for b in h.boxes:
            draw.rectangle((b[0] - x0 - 4, b[1] - y0 - 4, b[2] - x0 + 4, b[3] - y0 + 4), outline=TIER_HEX[h.tier],
                           width=5)
    crop.thumbnail((max_w, max_w * 2))
    buf = io.BytesIO()
    crop.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def write_pdf(path, pages, flagged, summary_lines):
    doc = fitz.open()
    # summary page
    sp = doc.new_page(width=595, height=842)
    y = 50
    for line, size, rgb in summary_lines:
        for chunk in [line[k:k + 95] for k in range(0, max(len(line), 1), 95)]:
            if y > 800:
                sp = doc.new_page(width=595, height=842)
                y = 50
            sp.insert_text((40, y), chunk, fontsize=size, color=rgb)
            y += size + 5
    for pno, (img, words) in enumerate(pages, 1):
        scale = 72 / 150  # 150 dpi page size
        w, h = img.width * scale, img.height * scale
        page = doc.new_page(width=w, height=h)
        small = img.copy()
        small.thumbnail((3200, 3200))
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=82)
        page.insert_image(page.rect, stream=buf.getvalue())
        # invisible OCR text so the PDF is searchable
        for wd in words:
            x0, y0, x1, y1 = (v * scale for v in wd.box)
            fs = max(3, (y1 - y0) * 0.85)
            try:
                page.insert_text((x0, y1 - (y1 - y0) * 0.15), wd.text, fontsize=fs, render_mode=3)
            except Exception:
                pass
        for hit in (x for x in flagged if x.page == pno):
            for b in hit.boxes:
                r = fitz.Rect(*(v * scale for v in b)) + (-3, -3, 3, 3)
                page.draw_rect(r, color=TIER_RGB[hit.tier], fill=TIER_RGB[hit.tier], fill_opacity=0.22, width=2)
            r = fitz.Rect(*(v * scale for v in hit.boxes[0]))
            page.insert_text((r.x0, max(r.y0 - 6, 8)), f"{hit.tier}: {hit.term}", fontsize=9, color=TIER_RGB[hit.tier])
    doc.save(path, garbage=3, deflate=True)


def _readers(h):
    ocr = len(h.passes - {VISION})
    parts = [f"{ocr} OCR pass{'es' if ocr > 1 else ''}"] if ocr else []
    return " + ".join(parts + (["Claude"] if VISION in h.passes else []))


def write_html(path, src_name, groups, all_pins, page_info, ocr_text, imgs, claude_status, vision_notices):
    n = {t: sum(1 for g in groups for h in g if h.tier == t) for t in TIERS}
    cards = []
    for gi, g in enumerate(groups, 1):
        best = min((h.tier for h in g), key=TIERS.index)
        r = _union([h.region for h in g] + [b for h in g for b in h.boxes])
        im = imgs[g[0].page - 1]
        region = (max(0, r[0] - 120), max(0, r[1] - 160), min(im.width, r[2] + 120), min(im.height, r[3] + 160))
        rows = "".join(
            f"<tr><td><span class=chip style='background:{TIER_HEX[h.tier]}'>{h.tier}</span></td>"
            f"<td><b>{html.escape(h.term)}</b><br><small>{html.escape(h.area)}</small></td>"
            f"<td><code>{html.escape(h.seen)}</code><br><small>{html.escape(h.note)}"
            f"{' · near an advocate/office signature' if h.signatory else ''}"
            f" · read by {_readers(h)}</small></td></tr>"
            for h in sorted(g, key=lambda h: TIERS.index(h.tier)))
        ctx = max(g, key=lambda h: len(h.context)).context
        cards.append(f"""
<section class=card id=n{gi}>
  <h3><span class=chip style='background:{TIER_HEX[best]}'>{best}</span> Notice {gi} · page {g[0].page}</h3>
  <table class=hits>{rows}</table>
  <details open><summary>Picture</summary><img src="data:image/jpeg;base64,{_crop(imgs[g[0].page - 1], region, g)}"></details>
  <details><summary>OCR text around the hit</summary><p class=ctx>{ctx}</p></details>
</section>""")
    pin_rows = "".join(
        f"<tr><td>{p}</td><td>{html.escape(a)}</td><td>{pg}</td><td>{'<b>flagged</b>' if f else ''}</td></tr>"
        for (p, pg), (a, f) in sorted(all_pins.items()))
    info_rows = "".join(
        f"<tr><td>{i}</td><td>{r}°</td><td>{html.escape(m)}</td><td>{nw}</td><td>{c:.0f}</td>"
        f"<td>{'<b>low – check this page by eye</b>' if c < 70 else ''}</td></tr>"
        for i, (r, m, nw, c) in enumerate(page_info, 1))
    vision_rows = "".join(
        f"<tr><td>{p}</td><td>{html.escape(n['heading'])}{' <b>(cut off)</b>' if n['cut_off'] else ''}</td>"
        f"<td>{'<br>'.join(map(html.escape, n['subject_locations']))}"
        f"{'<br><small>Signatory: ' + html.escape('; '.join(n['signatory_locations'])) + '</small>' if n['signatory_locations'] else ''}</td>"
        f"<td>{', '.join(map(html.escape, n['pincodes']))}</td></tr>" for p, n in vision_notices)
    texts = "".join(f"<details><summary>Page {i}</summary><pre>{html.escape(t)}</pre></details>"
                    for i, t in enumerate(ocr_text, 1))
    doc = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Notice Scan Report</title>
<style>
:root{{--bg:#fafafa;--fg:#1a1a1a;--card:#fff;--line:#ddd;--muted:#666}}
@media (prefers-color-scheme:dark){{:root:not([data-theme=light]){{--bg:#141414;--fg:#eee;--card:#1e1e1e;--line:#333;--muted:#aaa}}}}
:root[data-theme=dark]{{--bg:#141414;--fg:#eee;--card:#1e1e1e;--line:#333;--muted:#aaa}}
body{{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0;padding:16px;max-width:1100px;margin:auto}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin:14px 0}}
.chip{{color:#fff;border-radius:4px;padding:1px 7px;font-size:12px;font-weight:600}}
table{{border-collapse:collapse;width:100%}} td,th{{border-bottom:1px solid var(--line);padding:5px;text-align:left;vertical-align:top}}
img{{max-width:100%;border-radius:6px;margin-top:6px}} small{{color:var(--muted)}}
mark{{background:#ffe066;color:#000}} pre{{white-space:pre-wrap;font-size:12px}} .ctx{{font-size:13px}}
.sum span{{display:inline-block;margin-right:14px}}
</style></head><body>
<h1>Notice scan: {html.escape(src_name)}</h1>
<p class=sum><span><span class=chip style='background:{TIER_HEX["HIGH"]}'>HIGH</span> {n['HIGH']}</span>
<span><span class=chip style='background:{TIER_HEX["MEDIUM"]}'>MEDIUM</span> {n['MEDIUM']}</span>
<span><span class=chip style='background:{TIER_HEX["REVIEW"]}'>REVIEW</span> {n['REVIEW']}</span>
<span>{len(groups)} notice(s) with a hit</span></p>
<p><small>HIGH = target pincode or target area/road/building read exactly. MEDIUM = close OCR match or a common word.
REVIEW = neighbouring area, border pincode, or a loose match. OCR cannot read what was not photographed:
notices cut off at the photo edge are only partly checked.</small></p>
{''.join(cards) if cards else '<p class=card><b>No hits on target areas in this file.</b> Check the pincode table and page quality below.</p>'}
<h2>Every notice Claude read</h2><div class=card><p><small>Second reader: {html.escape(claude_status)}</small></p>
<table><tr><th>Page</th><th>Notice</th><th>Locations</th><th>Pincodes</th></tr>{vision_rows}</table></div>
<h2>Every pincode read</h2><div class=card><table><tr><th>Pincode</th><th>Area (approx.)</th><th>Page</th><th></th></tr>{pin_rows}</table></div>
<h2>Pages</h2><div class=card><table><tr><th>Page</th><th>Turned</th><th>How</th><th>Words</th><th>Mean OCR confidence</th><th></th></tr>{info_rows}</table></div>
<h2>Full OCR text</h2><div class=card>{texts}</div>
</body></html>"""
    Path(path).write_text(doc)


# ---------------------------------------------------------------- Claude second reader

def read_with_claude(img, pno, T, page_area, vision_notices):
    import vision
    hits = []
    for tile_box, notice in vision.read_page(img):
        vision_notices.append((pno, notice))
        texts = [(t, False) for t in notice["subject_locations"]] + \
                [(t, True) for t in notice["signatory_locations"]] + [(p, False) for p in notice["pincodes"]]
        for text, signatory in texts:
            words = [Word(tok, 100.0, tile_box) for tok in text.split()]
            if not words:
                continue
            for h in match_block(words, pno, VISION, T, page_area):
                h.signatory = h.signatory or signatory
                h.context = "Claude read: " + html.escape(text) + (" (notice cut off at photo edge)"
                                                                  if notice["cut_off"] else "")
                h.note = (h.note + "; " if h.note else "") + "Claude vision"
                hits.append(h)
    return hits


# ---------------------------------------------------------------- main

def page_area_fn(img_w, img_h):
    def region(words):
        b = _union(w.box for w in words)
        pad = 40
        b = (b[0] - pad, b[1] - pad, b[2] + pad, b[3] + pad)
        # very large blocks (whole columns) – keep the crop readable
        if (b[2] - b[0]) * (b[3] - b[1]) > 0.35 * img_w * img_h:
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            b = (cx - 900, cy - 700, cx + 900, cy + 700)
        return (max(0, b[0]), max(0, b[1]), min(img_w, b[2]), min(img_h, b[3]))
    return region


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pdf")
    ap.add_argument("-o", "--out", help="output folder (default: <pdf name>_scan next to the PDF)")
    ap.add_argument("--targets", default=str(HERE / "targets.json"))
    ap.add_argument("--fast", action="store_true", help="2 OCR passes instead of 7")
    ap.add_argument("--claude", choices=["auto", "on", "off"], default="auto",
                    help="second reader via the Claude API (auto = on when ANTHROPIC_API_KEY is set)")
    args = ap.parse_args()
    use_claude = args.claude == "on" or (args.claude == "auto" and (
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")))
    claude_status = "not run (no ANTHROPIC_API_KEY; run with --claude on to force)" if not use_claude else "ran"
    vision_notices = []

    src = Path(args.pdf)
    out = Path(args.out) if args.out else src.with_name(src.stem + "_scan")
    out.mkdir(parents=True, exist_ok=True)
    T = Targets(args.targets)

    all_hits, pages_for_pdf, page_info, ocr_text, imgs, layouts = [], [], [], [], [], []
    for pno, raw in enumerate(page_images(src), 1):
        t0 = time.time()
        img, rot, how = upright(raw)
        imgs.append(img)
        region = page_area_fn(img.width, img.height)
        passes = ocr_passes(img, fast=args.fast)
        for pname, blocks in passes:
            for words in blocks:
                all_hits += match_block(words, pno, pname, T, region)
        # notice outlines for grouping/cropping: paragraph blocks from the plain layout pass
        layouts.append([region(words) for words in passes[0][1]])
        base_words = [w for words in passes[0][1] for w in words]
        confs = [w.conf for w in base_words if w.conf >= 0]
        page_info.append((rot, how, len(base_words), sum(confs) / len(confs) if confs else 0))
        pages_for_pdf.append((img, base_words))
        ocr_text.append("\n\n".join(" ".join(w.text for w in words) for words in passes[0][1]))
        if use_claude:
            try:
                all_hits += read_with_claude(img, pno, T, region, vision_notices)
            except Exception as e:  # keep the OCR result even if the API is unreachable
                use_claude, claude_status = False, f"failed on page {pno}: {type(e).__name__}: {e}"
                print(f"Claude second reader {claude_status} – continuing with OCR only", file=sys.stderr)
        print(f"page {pno}: turned {rot}°, {len(base_words)} words, {time.time() - t0:.0f}s", file=sys.stderr)

    hits = merge(all_hits)
    for h in hits:
        h.region = _notice_region(h, layouts[h.page - 1])
    flagged = [h for h in hits if h.tier]
    all_pins = {}
    for h in hits:
        if h.kind == "pincode":
            key = (h.term, h.page)
            all_pins[key] = (h.area, all_pins.get(key, ("", False))[1] or bool(h.tier))
    groups = group_notices(flagged)

    stem = src.stem
    with open(out / f"{stem}_hits.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["notice", "page", "tier", "kind", "term", "area", "ocr_read", "note", "near_signature",
                     "read_by", "x0", "y0", "x1", "y1"])
        for gi, g in enumerate(groups, 1):
            for h in g:
                wr.writerow([gi, h.page, h.tier, h.kind, h.term, h.area, h.seen, h.note, h.signatory,
                             _readers(h), *(int(v) for v in h.box)])
    (out / f"{stem}_ocr.txt").write_text("\n\n".join(f"===== PAGE {i} =====\n{t}" for i, t in enumerate(ocr_text, 1)))

    summary = [(f"Notice scan: {src.name}", 16, (0, 0, 0)),
               (f"{len(groups)} notice(s) with a hit · " + " · ".join(
                   f"{t} {sum(1 for h in flagged if h.tier == t)}" for t in TIERS), 11, (0, 0, 0)), ("", 8, (0, 0, 0))]
    for gi, g in enumerate(groups, 1):
        for h in sorted(g, key=lambda h: TIERS.index(h.tier)):
            summary.append((f"Notice {gi} · p{h.page} · {h.tier} · {h.term} ({h.area}) · read as '{h.seen}'"
                            f"{' · signature' if h.signatory else ''}", 9, TIER_RGB[h.tier]))
    if not groups:
        summary.append(("No hits on target areas. See the HTML report for every pincode read.", 11, (0, 0, 0)))
    write_pdf(out / f"{stem}_highlighted.pdf", pages_for_pdf, flagged, summary)
    write_html(out / f"{stem}_report.html", src.name, groups, all_pins, page_info, ocr_text, imgs,
               claude_status, vision_notices)

    print(f"\n{len(groups)} notice(s) with a hit → {out}/")
    for gi, g in enumerate(groups, 1):
        for h in sorted(g, key=lambda h: TIERS.index(h.tier)):
            print(f"  [{gi}] p{h.page} {h.tier:<6} {h.term:<28} read '{h.seen}'  {h.note}")


if __name__ == "__main__":
    main()
