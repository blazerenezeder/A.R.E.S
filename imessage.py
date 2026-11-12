"""
imessage.py — text Blaze through the Messages app on the Mac A.R.E.S. runs on.

A bridge until Twilio's carrier registration clears: free, no registration,
real texts to a real phone. macOS only.

Sending drives Messages.app with AppleScript. Receiving reads Messages' own
database (~/Library/Messages/chat.db) read-only and picks up new incoming
messages from ARES_IMESSAGE_TO.

One-time setup on the always-on Mac:
  1. Sign Messages into an Apple ID that is NOT the one on Blaze's phone
     (texting yourself makes every message look like it came from you).
  2. System Settings → Privacy & Security → Full Disk Access: add the python3
     that runs A.R.E.S. (so it can read chat.db).
  3. Run `python3 imessage.py test` once from Terminal and click Allow on the
     "control Messages" prompt.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import subprocess
import time
from typing import Callable, Optional

log = logging.getLogger("ARES")

CHAT_DB = os.path.expanduser("~/Library/Messages/chat.db")
POLL_SECONDS = 5

# Text is passed as an argument, not pasted into the script, so quotes and
# newlines in a cover letter can't break it. `participant` is the name on
# macOS 13+; `buddy` on older systems.
_SEND_SCRIPT = """
on run argv
    set theHandle to item 1 of argv
    set theText to item 2 of argv
    tell application "Messages"
        set theService to 1st account whose service type = iMessage
        try
            send theText to participant theHandle of theService
        on error
            send theText to buddy theHandle of theService
        end try
    end tell
end run
"""


def recipient() -> str:
    return os.getenv("ARES_IMESSAGE_TO", "").strip()


def enabled() -> bool:
    return bool(recipient())


def send(body: str) -> bool:
    to = recipient()
    if not to:
        log.warning("iMessage not configured (ARES_IMESSAGE_TO) — message not sent")
        return False
    try:
        r = subprocess.run(
            ["osascript", "-e", _SEND_SCRIPT, to, body],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode != 0:
            log.error(f"iMessage failed: {r.stderr.strip()}")
            return False
        log.info("iMessage sent")
        return True
    except Exception as e:
        log.error(f"iMessage failed: {e}")
        return False


# ── Receiving ────────────────────────────────────────────────────────────────

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _same_handle(a: str, b: str) -> bool:
    """+1 (415) 555-1234 and 4155551234 are the same phone; emails match exactly."""
    if "@" in a or "@" in b:
        return a.strip().lower() == b.strip().lower()
    da, db = _digits(a), _digits(b)
    return len(da) >= 10 and len(db) >= 10 and da[-10:] == db[-10:]


def _decode_attributed_body(blob: Optional[bytes]) -> str:
    """Newer macOS leaves message.text empty and stores the text in an
    NSAttributedString blob. Pull the plain string out of it."""
    if not blob:
        return ""
    try:
        b = blob.split(b"NSString", 1)[1][5:]
        if b[0] == 0x81:
            length = int.from_bytes(b[1:3], "little")
            b = b[3:]
        else:
            length = b[0]
            b = b[1:]
        return b[:length].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _connect(db_path: str) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)


def latest_rowid(db_path: str = CHAT_DB) -> int:
    with _connect(db_path) as con:
        row = con.execute("SELECT MAX(ROWID) FROM message").fetchone()
    return row[0] or 0


def new_messages(after_rowid: int, db_path: str = CHAT_DB) -> tuple[list[str], int]:
    """Texts from Blaze newer than after_rowid (oldest first), plus the newest
    ROWID looked at, so the next call starts after everything seen here."""
    to = recipient()
    with _connect(db_path) as con:
        rows = con.execute(
            """
            SELECT m.ROWID, m.text, m.attributedBody, m.is_from_me, h.id
            FROM message m LEFT JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.ROWID > ?
            ORDER BY m.ROWID
            """,
            (after_rowid,),
        ).fetchall()
    out, last = [], after_rowid
    for rowid, text, attributed, from_me, handle in rows:
        last = rowid
        if from_me or not handle or not _same_handle(handle, to):
            continue
        body = (text or _decode_attributed_body(attributed)).strip()
        if body:
            out.append(body)
    return out, last


def poll(on_message: Callable[[str], None], db_path: str = CHAT_DB):
    """Run forever: call on_message(text) for each new text from Blaze.
    Starts from the newest message so old texts aren't replayed on restart."""
    try:
        last = latest_rowid(db_path)
    except Exception as e:
        log.error(f"iMessage can't read {db_path} ({e}). Give python3 Full Disk Access.")
        return
    log.info(f"iMessage listening for texts from {recipient()}...")
    while True:
        try:
            texts, last = new_messages(last, db_path)
            for body in texts:
                on_message(body)
        except Exception as e:
            log.error(f"iMessage polling error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        ok = send("A.R.E.S. test text. Reply anything and check ares.log.")
        print("sent" if ok else "failed (see log above)")
        try:
            print(f"chat.db readable, newest message id {latest_rowid()}")
        except Exception as e:
            print(f"can't read chat.db: {e} (give python3 Full Disk Access)")
    else:
        print("usage: python3 imessage.py test")
