#!/usr/bin/env python3
"""End-to-end check: build a fake photographed notice page, scan it, verify hits and non-hits.

    python3 selftest.py

The page is rotated, shadowed, blurred and JPEG-compressed to look like a phone photo, and
contains target mentions (some deliberately misspelt) plus look-alike decoys that must stay quiet.
"""
import csv
import sys
import tempfile
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FONT = "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"

NOTICES = [
    "PUBLIC NOTICE. Notice is hereby given that our client intends to purchase Flat No. 1202, 12th Floor, "
    "Sagar Tarang, Cuffe Parade, Colaba, Mumbai - 400 005 from the owner. Any person having any claim "
    "shall lodge the same within 14 days. Sd/- Advocate High Court, Mumbai 400013.",
    "PUBLIC NOTICE. All that piece of land bearing C.S. No. 1490 of Fort Division, situate at Bazargate "
    "Street, Fort, Mumbai 400001 together with the building standing thereon. Claims in writing to the "
    "undersigned within 15 days.",
    "TAKE NOTICE that the original share certificate of Office No. 41, Maker Chambers IV, Nariman Point, "
    "Mumbai 400021 has been lost. The society shall issue a duplicate. Effort to trace it has failed.",
    "NOTICE: Flat No. 5, Kapur Mahal, Netaji Subhash Chandra Bose Road, Marine Drive, Mumbai 400020, "
    "near Churchgate station. The heirs of the late owner have applied for transfer of shares. "
    "Sd/- Advocates, 12 Hamam Street, Fort, Mumbai 400023.",
    "E-AUCTION SALE NOTICE. Bank of India, Mumbai South Zone, Add: Bank of India Building, First Floor, "
    "Mahatma Gandhi Road, Fort, Mumbai 400001. Sale of Flat No. 906, 9th Floor, Virat Grandeur, Dombivli.",
    "IN THE DEBT RECOVERY TRIBUNAL NO. 2 AT MUMBAI, 3rd Floor, Telephone Bhavan, Colaba Market, Colaba, "
    "Mumbai 400005. State Bank of India versus Alisail Logistics Pvt. Ltd., Sakinaka, Andheri East.",
    "NOTICE (misprints on purpose): Shop at Cufe Parade and office at Nariman Poimt, Mumbai 4OOO21.",
    "DECOYS: Celestia Spaces Co-operative Housing Society, Sewree West Mumbai 400015. Comfort Lodge, "
    "Kandivali (East), Mumbai 400101. Advocate High Court. Effort and comfort are not places.",
]
MUST_FIND = {  # term -> lowest acceptable tier
    "Cuffe Parade": "MEDIUM", "Colaba": "HIGH", "400005": "HIGH", "Fort Division": "HIGH",
    "Bazargate Street": "MEDIUM", "400001": "HIGH", "Maker Chambers": "MEDIUM", "Nariman Point": "MEDIUM",
    "400021": "HIGH", "Kapur Mahal": "MEDIUM", "Netaji Subhash Chandra Bose Road": "MEDIUM",
    "Marine Drive": "HIGH", "400020": "HIGH", "Churchgate Station": "MEDIUM",
}
MUST_NOT_FIND = {"400015", "400101", "400013", "Cooperage", "Fort House"}
# is the place the property, or the address of whoever placed the notice?
MUST_BE_PROPERTY = {"Cuffe Parade", "Fort Division", "Maker Chambers", "Kapur Mahal", "Marine Drive"}
MUST_BE_OFFICE = {"Mahatma Gandhi Road", "Hamam Street", "400023"}
RANK = {"HIGH": 0, "MEDIUM": 1, "REVIEW": 2}


def make_page(path):
    font = ImageFont.truetype(FONT, 30)
    page = Image.new("L", (2600, 3400), 238)
    draw = ImageDraw.Draw(page)
    y = 80
    for text in NOTICES:
        lines = textwrap.wrap(text, 70)
        draw.rectangle((70, y - 20, 1500, y + 40 * len(lines) + 10), outline=40, width=3)
        for line in lines:
            draw.text((90, y), line, font=font, fill=25)
            y += 40
        y += 70
    # phone-photo damage: slight tilt, shadow, blur, noise, sideways, JPEG
    page = page.rotate(1.2, expand=False, fillcolor=238, resample=Image.BICUBIC)
    arr = np.array(page, dtype=np.float32)
    arr *= np.linspace(0.65, 1.0, arr.shape[1])[None, :]
    arr += np.random.default_rng(0).normal(0, 6, arr.shape)
    page = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8))
    page = page.rotate(90, expand=True)
    jpg = path.with_suffix(".jpg")
    page.convert("RGB").save(jpg, quality=70)
    img = Image.open(jpg)
    img.save(path, "PDF", resolution=72)


def fake_claude(img, client=None):
    """Stands in for the Claude API: one notice OCR also sees, one only 'Claude' sees."""
    yield (0, 0, img.width // 2, img.height // 2), {
        "heading": "TAKE NOTICE", "subject_locations": ["Office No. 41, Maker Chambers IV, Nariman Point"],
        "signatory_locations": [], "pincodes": ["400021"], "cut_off": False}
    yield (img.width // 2, 0, img.width, img.height // 2), {
        "heading": "PUBLIC NOTICE", "subject_locations": ["Flat 3, Sea View, Wodehouse Road, Colaba"],
        "signatory_locations": ["Advocate, Kandivali (East), Mumbai 400101"], "pincodes": ["400005"],
        "cut_off": True}


def run_scan(pdf, out, claude):
    """Run scan.py in-process so the Claude reader can be replaced by fake_claude."""
    import scan
    import vision
    vision.read_page = fake_claude
    sys.argv = ["scan.py", str(pdf), "-o", str(out), "--jobs", "1", "--claude", "on" if claude else "off"]
    scan.main()
    rows = list(csv.DictReader(open(Path(out) / "sample_hits.csv")))
    # one picture page per notice found, after a cover page
    pages = scan.fitz.open(Path(out) / "sample_NOTICES.pdf").page_count
    notices = len({r["notice"] for r in rows})
    print(f"{'ok ' if pages == notices + 1 else 'FAIL'} NOTICES.pdf has {pages - 1} notice page(s) for {notices} notice(s)")
    if pages != notices + 1:
        sys.exit(1)
    return rows


def main():
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp) / "sample.pdf"
        make_page(pdf)
        rows = run_scan(pdf, tmp, claude=False)
        rows_claude = run_scan(pdf, tmp, claude=True)
    best = {}
    for r in rows:
        if r["term"] not in best or RANK[r["tier"]] < RANK[best[r["term"]]]:
            best[r["term"]] = r["tier"]
    ok = True
    for term, worst in MUST_FIND.items():
        got = best.get(term)
        good = got is not None and RANK[got] <= RANK[worst]
        ok &= good
        print(f"{'ok ' if good else 'MISS'} {term:<34} {got or '-'} (need {worst} or better)")
    misspelt = {"Cuffe Parade", "Nariman Point", "400021"}
    print("misspelt copies flagged:", sum(1 for r in rows if r["term"] in misspelt) > len(misspelt))
    for term in MUST_NOT_FIND:
        bad = term in best
        ok &= not bad
        print(f"{'FALSE' if bad else 'ok   '} decoy {term} {'flagged as ' + best[term] if bad else 'stayed quiet'}")
    # with the (fake) Claude reader: its extra find appears, and shared finds merge into OCR's boxes
    only_claude = [r for r in rows_claude if r["term"] == "Wodehouse Road"]
    shared = [r for r in rows_claude if r["term"] == "Nariman Point" and "Claude" in r["read_by"]]
    dupes = len([r for r in rows_claude if r["term"] == "Nariman Point"]) - \
        len([r for r in rows if r["term"] == "Nariman Point"])
    good = bool(only_claude) and bool(shared) and "OCR" in shared[0]["read_by"] and dupes == 0
    ok &= good
    print(f"{'ok ' if good else 'FAIL'} Claude reader: extra find {bool(only_claude)}, "
          f"merged with OCR {bool(shared) and 'OCR' in shared[0]['read_by']}, duplicates {dupes}")
    roles = {}
    for r in rows:
        roles.setdefault(r["term"], set()).add(r["role"])
    for term in MUST_BE_PROPERTY:
        good = "property" in roles.get(term, set())
        ok &= good
        print(f"{'ok ' if good else 'FAIL'} {term} read as the property {sorted(roles.get(term, []))}")
    for term in MUST_BE_OFFICE:
        good = roles.get(term) == {"office"}
        ok &= good
        print(f"{'ok ' if good else 'FAIL'} {term} read as an office address {sorted(roles.get(term, []))}")
    good = {"property", "office"} <= roles.get("Colaba", set())
    ok &= good
    print(f"{'ok ' if good else 'FAIL'} Colaba: a flat in one notice, the tribunal's office in another "
          f"{sorted(roles.get('Colaba', []))}")
    print("PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
