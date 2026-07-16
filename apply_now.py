#!/usr/bin/env python3
"""
apply_now.py — One-shot runner to apply to all approved jobs in ares_pending.json.
Greenhouse jobs: auto-fill via Playwright (form stays open, awaits YES/NO via Telegram).
Other jobs: open in browser (manual).
"""
import sys
import os
import json
import webbrowser
import threading

sys.path.insert(0, os.path.dirname(__file__))

# Bootstrap ares globals before importing functions
import ares

PENDING_FILE = os.path.join(os.path.dirname(__file__), "ares_pending.json")

def load_jobs():
    with open(PENDING_FILE) as f:
        return json.load(f)

def main():
    jobs = load_jobs()
    approved = [j for j in jobs if j.get("status") == "approved"]

    if not approved:
        print("No approved jobs in queue.")
        return

    print(f"Found {len(approved)} approved job(s). Starting applies...\n")

    for i, job in enumerate(approved, 1):
        title = job.get("title", "Unknown")
        company = job.get("company", "Unknown")
        link = job.get("link", "")
        print(f"[{i}/{len(approved)}] {title} @ {company}")

        if ares.is_greenhouse_job(job):
            print(f"  → Greenhouse auto-fill via Playwright")
            t = threading.Thread(target=ares.greenhouse_apply, args=(job,), daemon=False)
            t.start()
            print(f"  → Browser opened. Check screen, verify form, then reply YES or NO via Telegram.")
            t.join()  # wait for this one before opening the next
        elif ares.is_ashby_job(job):
            print(f"  → Ashby auto-fill via Playwright")
            t = threading.Thread(target=ares.ashby_apply, args=(job,), daemon=False)
            t.start()
            t.join()
        else:
            print(f"  → Manual apply — opening in browser: {link}")
            webbrowser.open(link)
            ares.send_telegram(
                f"Manual apply needed:\n{title} @ {company}\n{link}\n\n"
                f"Name: {ares.CANDIDATE['name']}\n"
                f"Email: {ares.CANDIDATE['email']}\n"
                f"Phone: {ares.CANDIDATE['phone']}\n\n"
                f"Reply CL for cover letter."
            )
        print()

    print("All done.")

if __name__ == "__main__":
    main()
