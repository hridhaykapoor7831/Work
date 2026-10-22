#!/usr/bin/env bash
# One-time: let the GitHub notice-scan job read and write your Google Drive "NoticeScanner" folder.
#
#   curl -fsSL https://raw.githubusercontent.com/hridhaykapoor7831/Work/HEAD/newspaper-ocr/setup_drive.sh | bash
#
# 1. downloads rclone into ~/.notice-scanner (nothing installed system-wide, no password needed)
# 2. opens your browser: sign in to Google and click Allow
# 3. checks it can see NoticeScanner/Inbox
# 4. copies the Drive key to your clipboard and opens the GitHub page where you paste it
set -euo pipefail

REPO="hridhaykapoor7831/Work"
DIR="$HOME/.notice-scanner"
mkdir -p "$DIR"
export RCLONE_CONFIG="$DIR/rclone.conf"

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PKG=osx-arm64 ;;
  Darwin-x86_64) PKG=osx-amd64 ;;
  Linux-x86_64) PKG=linux-amd64 ;;
  Linux-aarch64) PKG=linux-arm64 ;;
  *) echo "This computer type isn't supported by this script: $(uname -s) $(uname -m)"; exit 1 ;;
esac

RCLONE="$DIR/rclone"
if [ ! -x "$RCLONE" ]; then
  echo "• Downloading rclone…"
  curl -fsSL "https://downloads.rclone.org/rclone-current-$PKG.zip" -o "$DIR/rclone.zip"
  rm -rf "$DIR/unzip"
  unzip -q "$DIR/rclone.zip" -d "$DIR/unzip"
  mv "$(find "$DIR/unzip" -type f -name rclone | head -1)" "$RCLONE"
  chmod +x "$RCLONE"
  rm -rf "$DIR/unzip" "$DIR/rclone.zip"
fi

echo
echo "• A browser tab will open. Sign in to the Google account that has the NoticeScanner folder,"
echo "  then click Allow. Come back here when the tab says Success."
echo
"$RCLONE" config create gdrive drive scope=drive < /dev/null > /dev/null  # stdin is this script under curl | bash

echo "• Checking your Drive…"
if ! "$RCLONE" lsf gdrive:NoticeScanner --dirs-only 2>/dev/null | grep -qx "Inbox/"; then
  echo "  Couldn't find NoticeScanner/Inbox in that account's My Drive."
  echo "  Create it (or sign in with the right account) and run this command again."
  exit 1
fi
echo "  Found NoticeScanner/Inbox."

"$RCLONE" config show gdrive > "$DIR/key.txt"
PASTE="paste (Cmd+V); the Drive key is already on your clipboard"
if command -v pbcopy > /dev/null; then
  pbcopy < "$DIR/key.txt"
elif command -v xclip > /dev/null; then
  xclip -selection clipboard < "$DIR/key.txt"
else
  echo "  Copy everything between the lines below:"; echo "-----"; cat "$DIR/key.txt"; echo "-----"
  PASTE="paste the text you copied above"
fi
rm -f "$DIR/key.txt"

URL="https://github.com/$REPO/settings/secrets/actions/new"
command -v open > /dev/null && open "$URL" || { command -v xdg-open > /dev/null && xdg-open "$URL"; } || true

cat <<EOF

• Last step, on the GitHub page that just opened ($URL):
    Name:    RCLONE_CONF
    Secret:  $PASTE
    then click "Add secret".

Done after that. Drop a PDF into NoticeScanner/Inbox; results appear in NoticeScanner/Results.
(Copy anything else afterwards so the key doesn't stay on your clipboard.)
EOF
