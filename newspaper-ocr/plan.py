#!/usr/bin/env python3
"""Pick the next newspaper from the Drive inbox and get it ready for the parallel scan.

    python3 plan.py <rclone remote> <work dir> [file]

- With no `file`: the oldest PDF in Inbox/. If Inbox/ has only photos (JPG/PNG), all of them
  together are one newspaper, in camera (file name) order, bundled into one PDF.
- With `file` (a path under the remote, e.g. "Processed/2026-11-17 Nov 17th.pdf"): that file,
  left where it is (test re-runs).

Writes <work dir>/edition.pdf and, for GitHub Actions, these outputs: n (pages, 0 = nothing to
do), shards (JSON list 1..N), stem, stamp, originals (JSON list of Inbox file names to move).
"""
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pymupdf as fitz

MAX_SHARDS = 20  # GitHub runs up to 20 jobs at once on the free plan
PHOTO = (".jpg", ".jpeg", ".png")


def rclone(*args):
    return subprocess.run(["rclone", *args], check=True, capture_output=True, text=True).stdout


def output(**kv):
    lines = [f"{k}={v}" for k, v in kv.items()]
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write("\n".join(lines) + "\n")
    print("\n".join(l for l in lines if not l.startswith("originals")))  # names stay out of public logs


def main():
    remote, work = sys.argv[1], Path(sys.argv[2])
    chosen = sys.argv[3].strip() if len(sys.argv) > 3 else ""
    work.mkdir(parents=True, exist_ok=True)
    edition = work / "edition.pdf"
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30))).strftime("%Y-%m-%d")

    if chosen:
        rclone("copyto", f"{remote}/{chosen}", str(edition))
        stem, originals = Path(chosen).stem, []
    else:
        files = json.loads(rclone("lsjson", f"{remote}/Inbox", "--files-only"))
        files.sort(key=lambda f: (f["ModTime"], f["Name"]))
        pdfs = [f["Name"] for f in files if f["Name"].lower().endswith(".pdf")]
        # photos go in camera order (IMG_0412 before IMG_0413), whatever order they finished uploading in
        photos = sorted((f["Name"] for f in files if f["Name"].lower().endswith(PHOTO)),
                        key=lambda n: [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", n)])
        if pdfs:
            originals = pdfs[:1]
            rclone("copyto", f"{remote}/Inbox/{pdfs[0]}", str(edition))
            stem = Path(pdfs[0]).stem
        elif photos:
            originals = photos
            for name in photos:
                rclone("copyto", f"{remote}/Inbox/{name}", str(work / "photos" / name))
            doc = fitz.open()
            for name in photos:  # each photo becomes a page at its own pixel size
                img = fitz.open(str(work / "photos" / name))
                rect = img[0].rect
                page = doc.new_page(width=rect.width, height=rect.height)
                page.insert_image(rect, filename=str(work / "photos" / name))
            doc.save(str(edition))
            stem = f"Photos ({len(photos)} pages)"
        else:
            output(n=0, shards="[]", stem="", stamp=stamp, originals="[]")
            return

    with fitz.open(str(edition)) as doc:
        n = doc.page_count
    # always the full 20: a short paper then finishes as fast as a long one (each machine gets less)
    shards = list(range(1, min(MAX_SHARDS, n * 8) + 1))
    output(n=n, shards=json.dumps(shards), stem=stem, stamp=stamp, originals=json.dumps(originals))


if __name__ == "__main__":
    main()
