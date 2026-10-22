#!/usr/bin/env bash
# Scan every PDF/photo waiting in $NOTICE_REMOTE/Inbox (any rclone remote, e.g. gdrive:NoticeScanner).
#   results   -> $NOTICE_REMOTE/Results/<date> <name>/
#   originals -> $NOTICE_REMOTE/Processed/  (or Failed/ if the scan crashed)
# Hit details stay out of stdout on purpose: CI logs of a public repo are public.
set -euo pipefail

REMOTE="${NOTICE_REMOTE:?set NOTICE_REMOTE, e.g. gdrive:NoticeScanner}"
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
INCLUDE='*.{pdf,PDF,jpg,JPG,jpeg,JPEG,png,PNG}'

mapfile -t FILES < <(rclone lsf "$REMOTE/Inbox" --files-only --include "$INCLUDE")
if [ "${#FILES[@]}" -eq 0 ]; then
  echo "Inbox empty"
  exit 0
fi

failed=0
for f in "${FILES[@]}"; do
  stamp="$(TZ=Asia/Kolkata date +%Y-%m-%d)"
  stem="${f%.*}"
  name="$stamp $stem"
  echo "== $f"
  rclone copy "$REMOTE/Inbox/$f" "$WORK/in/"
  if python3 "$HERE/scan.py" "$WORK/in/$f" -o "$WORK/out/$name" > "$WORK/scan.log"; then
    # scan.py names its outputs after the input file; prefix the date so daily uploads never collide
    rclone copy "$WORK/out/$name" "$REMOTE/Results/$name"
    rclone moveto "$REMOTE/Inbox/$f" "$REMOTE/Processed/$stamp $f"
    python3 "$HERE/notify.py" "$WORK/out/$name" "$stem" || echo "email not sent"
    echo "done: results in Results/$name"
  else
    rclone moveto "$REMOTE/Inbox/$f" "$REMOTE/Failed/$stamp $f"
    echo "::error::scan failed for $f (moved to Failed/)"
    failed=1
  fi
  rm -rf "$WORK/in" "$WORK/out"
done
exit "$failed"
