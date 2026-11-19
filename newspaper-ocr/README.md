# Newspaper notice scanner (South Mumbai targets)

Give it a PDF of phone photos of newspaper pages; it flags every notice that mentions
Cuffe Parade, Colaba, Nariman Point, Fort, Marine Drive, Churchgate, or anything inside them.

```
python3 scan.py Oct_21.pdf
```

Writes `Oct_21_scan/` next to the PDF:

| File | What it is |
|---|---|
| `Oct_21_NOTICES.pdf` | **Start here.** One page per notice found: a picture of the printed notice with your matches boxed, the page number and the section (in your areas / double-check / office address only). Opens directly in Google Drive. |
| `Oct_21_highlighted.pdf` | Summary page, then every page turned upright with hits boxed (red HIGH, orange MEDIUM, blue REVIEW). Text is searchable (Ctrl+F). |
| `Oct_21_report.html` | One card per notice: what matched, a cropped picture, the surrounding text. Also: every pincode read, every notice Claude read (if on), page quality. |
| `Oct_21_hits.csv` | One row per hit, for spreadsheets. |
| `Oct_21_ocr.txt` | Raw OCR text. |
| `Oct_21_summary.txt` | A few lines: notices hit and their terms (the email body). |

## Daily use: about 10 minutes from photo to result

1. **Scan the paper with your phone straight into Drive.** Google Drive app → **+** → **Scan**
   (on iPhone: the camera icon). Shoot every page, tap Save, choose folder
   `NoticeScanner/Inbox`. That's it: no computer, no PDF step, no GitHub.
   (Sending photos to `Inbox` from the gallery also works: all photos there become one newspaper,
   in camera order, once none has arrived for 2 minutes.)
2. **Wait for the result.** Within a minute the Drive trigger (`drive_trigger.gs`) starts the scan
   on GitHub. Up to 20 machines each read a share of the pages, then one combines them:
   `Results/<date> <name> - NOTICES.pdf` appears, the email arrives, and the original moves to
   `Processed/`.

The reading is exactly the same as the old one-machine scan (same 7 OCR passes per page, same
matching); only the work is spread out. `scan.py --merge` refuses to write a result if any machine's
share is missing, so a page can't be silently skipped.

```
NoticeScanner/
  Inbox/       ← newspapers land here (Drive scan PDF, or photos)
  Results/     ← one file per newspaper: "2026-10-27 <name> - NOTICES.pdf"
  Results/test ← test re-runs (Actions → Notice scan → Run workflow, with a file path)
  Processed/   ← originals move here once scanned
  Failed/      ← only if a scan crashed
```

The NOTICES PDF is the only thing to read: page 1 lists every notice found (page number and
verdict: IN YOUR AREAS / DOUBLE-CHECK / NOT YOUR AREA), then each notice gets a page with the
verdict, a picture of the notice with the matches boxed, and the newspaper page with that notice
outlined.

### One-time setup

1. **Drive folder.** In Google Drive create `NoticeScanner`, and inside it `Inbox`.
2. **Connect Drive to GitHub (one command).** On your Mac open Terminal and run:

   ```
   curl -fsSL https://raw.githubusercontent.com/hridhaykapoor7831/Work/HEAD/newspaper-ocr/setup_drive.sh | bash
   ```

   Sign in, click Allow, then on the GitHub page that opens add the secret `RCLONE_CONF` (Cmd+V).
3. **Email (optional).** Secrets `SMTP_USER`, `SMTP_PASSWORD` (Gmail App Password), `MAIL_TO`.
4. **Automatic start.**
   - GitHub → Settings (your profile) → Developer settings → Personal access tokens →
     **Fine-grained tokens** → Generate new token. Repository access: *Only select repositories* →
     `Work`. Permissions → Repository → **Actions: Read and write**. Generate, copy it.
   - Open https://script.google.com → New project → paste all of `drive_trigger.gs` over the
     sample code → save (name it "Notice scanner trigger").
   - Project Settings (gear) → Script Properties → Add: `GITHUB_TOKEN` = the token.
   - Back in the editor, pick `setup` in the function menu → Run → allow access. The log says
     "Ready". From then on the Inbox is checked every minute.

The schedule in `.github/workflows/notice-scan.yml` (every 2 hours, 6 am–10 pm IST) stays as a
safety net if the trigger ever stops. If several newspapers are waiting, each run starts the next.

Optional Claude second reader: add secret `ANTHROPIC_API_KEY`. It is billed per page by the
Claude API, so it is off unless that secret exists. Pick the model with repository variable
`CLAUDE_MODEL` (default `claude-opus-5-5`).

The repository is public so the 20 machines are free (GitHub gives private repositories 2,000
minutes a month; one newspaper uses about 200). Hit details are kept out of the public logs; the
target list in `targets.json` is visible.

### Running it on one computer

`python3 scan.py Oct_21.pdf` still does the whole scan on one machine (same output), and
`run_inbox.sh` still scans the inbox that way. The pieces the workflow uses:

```
python3 plan.py gdrive:NoticeScanner work            # pick the next newspaper -> work/edition.pdf
python3 scan.py work/edition.pdf --shard 3/20 --parts parts/3   # one machine's share
python3 scan.py --merge parts --name "Nov 19th" -o out          # combine (refuses if incomplete)
```

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
a match.

**Property or office?** Banks, tribunals and lawyers often have offices in Fort, Colaba and Nariman
Point, so a target address in a notice is not always the property. Each hit is judged from the words
around it:
- Property, when the hit is near "Flat / Shop / situated at / C.S. No. / admeasuring / Schedule".
  A land record like "of Fort Division" always counts as the property.
- Office, when the hit is near "Bank / Branch / Tribunal / Advocate / Regd. Office / Sd/- / Ltd",
  or next to a known office in `issuer_addresses` (e.g. "MTNL Building", the debt recovery
  tribunals' office in Colaba).

`summary.txt` then lists the page and what was found, in three sections:

```
IN YOUR AREAS (the property is here)
  Page 13: Colaba Division, Radio Club (Colaba), 400005 (Colaba)
DOUBLE-CHECK (open the notice: weak match, or can't tell property from office)
  Page 5: Bombay House (Fort)
OFFICE ADDRESSES ONLY (a bank, tribunal or lawyer in your area; the property is elsewhere)
  Page 24: Colaba, 400005 (Colaba)
```

Nothing is dropped: office-only notices are still listed, last. In the highlighted PDF they are
boxed in grey.

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
