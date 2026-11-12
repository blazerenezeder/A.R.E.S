"""
twilio_sms.py — text Blaze's real phone number over Twilio SMS.

Sending uses the Twilio Messages API. Receiving polls Twilio for new texts
from MY_PHONE to TWILIO_FROM, so no public webhook URL is needed.

US texting needs A2P 10DLC registration (or toll-free verification) in the
Twilio console before carriers deliver messages. Until it's approved,
sends may be blocked; check the message log in the console.

.env:
  TWILIO_SID=ACxxxxxxxx
  TWILIO_AUTH_TOKEN=xxxxxxxx
  TWILIO_FROM=+1XXXXXXXXXX   (the number you bought in Twilio)
  MY_PHONE=+1XXXXXXXXXX      (your phone)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Callable

log = logging.getLogger("ARES")

POLL_SECONDS = 10
SMS_CHUNK = 1500  # Twilio caps a message body at 1600 characters


def _config() -> tuple[str, str, str, str]:
    return (
        os.getenv("TWILIO_SID", "").strip(),
        os.getenv("TWILIO_AUTH_TOKEN", "").strip(),
        os.getenv("TWILIO_FROM", "").strip(),
        os.getenv("MY_PHONE", "").strip(),
    )


def enabled() -> bool:
    return all(_config())


def _client():
    from twilio.rest import Client
    sid, token, _, _ = _config()
    return Client(sid, token)


def send(body: str) -> bool:
    if not enabled():
        log.warning("Twilio not configured (TWILIO_SID / TWILIO_AUTH_TOKEN / TWILIO_FROM / MY_PHONE) — message not sent")
        return False
    _, _, from_, to = _config()
    try:
        client = _client()
        for i in range(0, len(body), SMS_CHUNK):
            client.messages.create(from_=from_, to=to, body=body[i:i + SMS_CHUNK])
        log.info("SMS sent")
        return True
    except Exception as e:
        log.error(f"SMS failed: {e}")
        return False


def _inbound(client) -> list:
    """Recent texts from Blaze to the A.R.E.S. number, newest first."""
    _, _, from_, to = _config()
    return client.messages.list(from_=to, to=from_, limit=20)


def poll(on_message: Callable[[str], None]):
    """Run forever: call on_message(text) for each new text from Blaze.
    Texts already in Twilio at startup are skipped so restarts don't replay them."""
    if not enabled():
        log.warning("Twilio not configured — not listening for texts")
        return
    client = _client()
    try:
        seen = {m.sid for m in _inbound(client)}
    except Exception as e:
        log.error(f"Twilio can't list messages ({e}) — check TWILIO_SID / TWILIO_AUTH_TOKEN")
        return
    log.info("Twilio listening for texts...")
    while True:
        try:
            for m in reversed(_inbound(client)):
                if m.sid in seen:
                    continue
                seen.add(m.sid)
                body = (m.body or "").strip()
                if body:
                    on_message(body)
        except Exception as e:
            log.error(f"Twilio polling error: {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    import sys
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        ok = send("A.R.E.S. test text. Reply anything and check ares.log.")
        print("sent" if ok else "failed (see log above)")
    else:
        print("usage: python3 twilio_sms.py test")
