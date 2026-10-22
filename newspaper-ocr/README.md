# Newspaper notice scanner (South Mumbai targets)

Give it a PDF of phone photos of newspaper pages; it flags every notice that mentions
Cuffe Parade, Colaba, Nariman Point, Fort, Marine Drive, Churchgate, or anything inside them.

```
python3 scan.py Oct_21.pdf
```

Writes `Oct_21_scan/` next to the PDF:

| File | What it is |
|---|---|
| `Oct_21_highlighted.pdf` | Summary page, then every page turned upright with hits boxed (red HIGH, orange MEDIUM, blue REVIEW). Text is searchable (Ctrl+F). |
| `Oct_21_report.html` | One card per notice: what matched, a cropped picture, the surrounding text. Also: every pincode read, every notice Claude read (if on), page quality. |
| `Oct_21_hits.csv` | One row per hit, for spreadsheets. |
| `Oct_21_ocr.txt` | Raw OCR text. |
| `Oct_21_summary.txt` | A few lines: notices hit and their terms (the email body). |

## Daily automatic scans (no Claude usage, any PDF size)

You drop the PDF into a Google Drive folder from your phone or computer. Within the hour, a
GitHub Actions job (free compute, not Claude) scans it and puts the results next to it in Drive.
It can also email you. Drive has no 30 MB upload limit, and pages are scanned one at a time
from disk, so file size is not a problem.

```
NoticeScanner/
  Inbox/       ← drop PDFs (or JPG/PNG photos) here
  Results/     ← "2026-10-22 Oct_22/": highlighted PDF, report, CSV, summary
  Processed/   ← originals move here once scanned
  Failed/      ← only if a scan crashed
```

One-time setup (about 10 minutes):

1. **Drive folder.** In Google Drive create `NoticeScanner`, and inside it `Inbox`.
2. **Drive key for the job.** On any computer: install rclone (`brew install rclone` on a Mac,
   or https://rclone.org/downloads/), run `rclone config`, then: `n` (new) → name `gdrive` →
   storage `drive` → leave client id/secret blank → scope `1` → accept defaults → "Use web browser" `y`
   → sign in to your Google account → shared drive `n` → `y` to keep. Then print the file with
   `rclone config show` (or open `~/.config/rclone/rclone.conf`) and copy the whole `[gdrive]` section.
3. **Give it to GitHub.** Repo → Settings → Secrets and variables → Actions → New repository secret:
   `RCLONE_CONF` = the text from step 2.
4. **Email (optional).** Add secrets `SMTP_USER` (your Gmail address), `SMTP_PASSWORD` (a Gmail
   App Password: Google Account → Security → 2-Step Verification → App passwords), `MAIL_TO`.
5. **Test.** Put a PDF in `Inbox`, then Actions tab → "Notice scan" → Run workflow.

After that it checks the inbox every hour, about 6 am to 10 pm IST. To change the hours, edit the
`cron` line in `.github/workflows/notice-scan.yml` (times are UTC).

Optional Claude second reader: add secret `ANTHROPIC_API_KEY`. It is billed per page by the
Claude API, so it is off unless that secret exists. Pick the model with repository variable
`CLAUDE_MODEL` (default `claude-opus-5-5`).

Keep the repository **private** if the target list or results are sensitive: logs of a public
repository are public (the job keeps hit details out of its logs, but `targets.json` is in the
repo), and GitHub pauses schedules in public repositories after 60 days without commits.

## How it reads

1. Each photo is turned upright (all 4 rotations tried; best wins).
2. Lighting is flattened, then Tesseract reads the page 7 different ways (scales, binarisation,
   layout modes). On the test photos the union recovered 58/59 probe words; the best single pass got 49.
3. Optional second reader: if `ANTHROPIC_API_KEY` is set, Claude reads each page in 4 overlapping
   tiles and lists every location in every notice. Its readings go through the same matcher.
   Force with `--claude on`, disable with `--claude off`.

## How it matches (`targets.json`)

| Layer | Example | Tier |
|---|---|---|
| Target pincode | 400001, 400005, 400020, 400021, 400023, 400032, 400038, 400039 | HIGH |
| Area / road / building / land-record name, read exactly | `Cuffe Parade`, `Fort Division`, `Maker Chambers`, `N S Road` | HIGH |
| Same, with OCR letter errors | `Cufe Parade`, `Nariman Poimt` | MEDIUM |
| Common word that is also a place | `Fort` with no "Mumbai"/pincode after it | MEDIUM |
| Neighbouring area, border pincode, loose match | `Marine Lines`, 400002, 400004 | REVIEW |
| Pincode that isn't a known Mumbai pincode, 1 digit from a target (likely misread) | `400041` | REVIEW |

Typo allowance comes from the distinctive part of a name only, so `Road`/`Building` can't carry
a match. Hits right after "Advocate"/"Sd/-" are tagged as the signatory's address.

Add names by editing `targets.json` (no code changes). `exact_only` lists names that look like
everyday words after OCR errors (`Cooperage` ≈ "co-operative").

## Setup

```
sudo apt-get install tesseract-ocr tesseract-ocr-eng
pip install -r requirements.txt
python3 selftest.py   # fake photographed page with targets + decoys; prints PASS/FAIL
```

## Limits

- It can only read what was photographed: a notice cut off at the photo edge is only partly checked.
  Shoot each half-page flat, in good light, with a margin around every column.
- Pincodes printed in Marathi/Hindi digits are not read (English only).
- Building names are a starter list; South Mumbai has far more buildings than are listed. Pincodes,
  area names and road names carry most of the recall.
