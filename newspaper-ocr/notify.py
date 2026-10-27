#!/usr/bin/env python3
"""Email one scan's summary, with the report attached.

    python3 notify.py <scan output folder> <name>

Needs SMTP_USER, SMTP_PASSWORD and MAIL_TO (comma-separated). For Gmail, SMTP_PASSWORD is an
App Password (Google Account → Security → App passwords). Does nothing if they aren't set.
"""
import os
import re
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

ATTACH_LIMIT = 20 * 1024 * 1024  # Gmail rejects mail over 25 MB


def main():
    folder, name = Path(sys.argv[1]), sys.argv[2]
    user, password, to = (os.environ.get(k, "") for k in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"))
    if not (user and password and to):
        print("email not configured (SMTP_USER / SMTP_PASSWORD / MAIL_TO)")
        return
    summary = next(folder.glob("*_summary.txt")).read_text()
    high, check = map(int, re.search(r"(\d+) notice\(s\) in your areas, (\d+) to double-check", summary).groups())
    if high:
        subject = f"⚠ {high} notice(s) in your areas"
    elif check:
        subject = f"{check} notice(s) to double-check"
    else:
        subject = "Nothing in your areas"
    msg = EmailMessage()
    msg["Subject"] = f"{subject}: {name}"
    msg["From"], msg["To"] = user, to
    msg.set_content(summary + "\nEach notice, with the page it came from, is in the attached PDF "
                    "(also in Results on Drive).\n")
    used = 0
    for pattern, kind in (("*_NOTICES.pdf", ("application", "pdf")),):
        for f in folder.glob(pattern):
            size = f.stat().st_size
            if used + size <= ATTACH_LIMIT:
                msg.add_attachment(f.read_bytes(), maintype=kind[0], subtype=kind[1], filename=f.name)
                used += size
    host, port = os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port) as s:
        s.login(user, password)
        s.send_message(msg)
    print("email sent")


if __name__ == "__main__":
    main()
