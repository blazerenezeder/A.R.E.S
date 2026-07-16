#!/usr/bin/env python3
"""
Bear Stack Job Tracker
Run: python3 tracker.py
Opens a browser with all your A.R.E.S. jobs — pending, approved, skipped.
"""

import json
import os
import webbrowser
import tempfile
from datetime import datetime

PENDING_FILE = os.path.join(os.path.dirname(__file__), "ares_pending.json")

def load_jobs():
    if not os.path.exists(PENDING_FILE):
        return []
    with open(PENDING_FILE) as f:
        return json.load(f)

def score_color(score):
    if score >= 9: return "#4aff4a"
    if score >= 7: return "#f0c040"
    return "#ff6644"

def status_badge(status):
    badges = {
        "pending": ('<span style="background:#2244aa;color:#aaccff;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:bold;">⏳ PENDING</span>', "#1a2a4a"),
        "approved": ('<span style="background:#1a4a1a;color:#4aff4a;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:bold;">✓ APPLIED</span>', "#1a2a1a"),
        "skipped": ('<span style="background:#3a2a2a;color:#aa6666;padding:3px 10px;border-radius:12px;font-size:11px;font-weight:bold;">✗ SKIPPED</span>', "#2a1a1a"),
    }
    return badges.get(status, badges["pending"])

def build_html(jobs):
    pending = [j for j in jobs if j.get("status") == "pending"]
    approved = [j for j in jobs if j.get("status") == "approved"]
    skipped = [j for j in jobs if j.get("status") == "skipped"]

    now = datetime.now().strftime("%a %b %d, %Y — %I:%M %p")

    cards = ""
    for i, job in enumerate(jobs):
        badge_html, card_bg = status_badge(job.get("status", "pending"))
        score = job.get("score", "?")
        sc = score_color(score) if isinstance(score, int) else "#888"
        cl = job.get("cover_letter", "").replace("`", "&#96;").replace("\\", "\\\\").replace("\n", "\\n").replace("'", "\\'")
        found = job.get("found_at", "")[:10] if job.get("found_at") else "Unknown"
        hm = job.get("hiring_manager", "")
        addr = job.get("company_address", "").replace("\n", ", ")
        job_num = i + 1

        cards += f"""
        <div style="background:{card_bg};border:1px solid #333;border-radius:10px;padding:20px 24px;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;">
                <div>
                    <div style="font-size:18px;font-weight:bold;color:#fff;margin-bottom:4px;">{job.get('title','Unknown')}</div>
                    <div style="font-size:14px;color:#aaa;margin-bottom:8px;">{job.get('company','')} &nbsp;·&nbsp; {job.get('location','')}</div>
                    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
                        {badge_html}
                        <span style="color:{sc};font-size:13px;font-weight:bold;">★ {score}/10</span>
                        <span style="color:#666;font-size:12px;">Found {found}</span>
                    </div>
                </div>
                <a href="{job.get('link','#')}" target="_blank" style="background:#333;color:#fff;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:12px;white-space:nowrap;">View Job ↗</a>
            </div>

            <div style="margin-top:12px;color:#bbb;font-size:13px;font-style:italic;">{job.get('reason','')}</div>

            {"<div style='margin-top:8px;font-size:12px;color:#888;'>Contact: " + hm + "</div>" if hm else ""}
            {"<div style='margin-top:4px;font-size:12px;color:#666;'>" + addr + "</div>" if addr else ""}

            <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap;">
                <button onclick="toggleCL({job_num})" style="background:#1a2a3a;color:#7ec8e3;border:1px solid #2a4a6a;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;">📄 Cover Letter</button>
                {"<a href='mailto:?subject=Application: " + job.get('title','') + " at " + job.get('company','') + "' style='background:#1a3a1a;color:#4aff4a;border:1px solid #2a5a2a;padding:6px 14px;border-radius:6px;text-decoration:none;font-size:12px;'>✉ Send Application</a>" if job.get("status") == "approved" else ""}
            </div>

            <div id="cl-{job_num}" style="display:none;margin-top:16px;background:#0d0d1a;border:1px solid #222;border-radius:6px;padding:16px;">
                <div style="font-size:11px;color:#666;margin-bottom:10px;text-transform:uppercase;letter-spacing:1px;">Cover Letter</div>
                <pre style="font-family:'Georgia',serif;font-size:13px;line-height:1.7;color:#ccc;white-space:pre-wrap;margin:0;">{job.get('cover_letter','Not generated yet.')}</pre>
                <button onclick="copyText({job_num})" style="margin-top:12px;background:#2a2a3a;color:#aaa;border:1px solid #444;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;">📋 Copy</button>
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bear Stack — Job Tracker</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#0d0a1a; color:#fff; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; min-height:100vh; padding:24px; }}
.header {{ border-bottom:1px solid #222; padding-bottom:16px; margin-bottom:24px; display:flex; justify-content:space-between; align-items:flex-end; flex-wrap:wrap; gap:10px; }}
.title {{ font-size:22px; font-weight:bold; color:#f0c040; letter-spacing:1px; }}
.subtitle {{ font-size:12px; color:#555; margin-top:4px; }}
.stats {{ display:flex; gap:20px; flex-wrap:wrap; }}
.stat {{ text-align:center; }}
.stat-num {{ font-size:24px; font-weight:bold; }}
.stat-lbl {{ font-size:11px; color:#666; text-transform:uppercase; letter-spacing:1px; }}
.section-title {{ font-size:12px; color:#666; text-transform:uppercase; letter-spacing:2px; margin:24px 0 12px; }}
.empty {{ color:#444; font-size:14px; padding:16px 0; }}
button:hover {{ opacity:0.85; }}
</style>
</head>
<body>

<div style="max-width:800px;margin:0 auto;">

    <div class="header">
        <div>
            <div class="title">◈ BEAR STACK — JOB TRACKER</div>
            <div class="subtitle">Last updated: {now} &nbsp;·&nbsp; Powered by A.R.E.S. + Maverick</div>
        </div>
        <div class="stats">
            <div class="stat"><div class="stat-num" style="color:#4488ff;">{len(pending)}</div><div class="stat-lbl">Pending</div></div>
            <div class="stat"><div class="stat-num" style="color:#4aff4a;">{len(approved)}</div><div class="stat-lbl">Applied</div></div>
            <div class="stat"><div class="stat-num" style="color:#aa4444;">{len(skipped)}</div><div class="stat-lbl">Skipped</div></div>
            <div class="stat"><div class="stat-num" style="color:#f0c040;">{len(jobs)}</div><div class="stat-lbl">Total</div></div>
        </div>
    </div>

    {"<div class='section-title'>⏳ Pending — Needs Decision</div>" + ("".join(cards_by_status(jobs, "pending")) or "<div class='empty'>No pending jobs. Send SCAN to Maverick to find new roles.</div>") if pending else "<div class='section-title'>⏳ Pending</div><div class='empty'>Queue is clear. Send SCAN to Maverick.</div>"}

    {"<div class='section-title'>✓ Applied</div>" + "".join(cards_by_status_html(jobs, "approved")) if approved else ""}

    {"<div class='section-title'>✗ Skipped</div>" + "".join(cards_by_status_html(jobs, "skipped")) if skipped else ""}

</div>

<script>
const jobs = {json.dumps(jobs)};

function toggleCL(n) {{
    const el = document.getElementById('cl-' + n);
    el.style.display = el.style.display === 'none' ? 'block' : 'none';
}}

function copyText(n) {{
    const el = document.getElementById('cl-' + n).querySelector('pre');
    navigator.clipboard.writeText(el.textContent).then(() => {{
        event.target.textContent = '✓ Copied';
        setTimeout(() => event.target.textContent = '📋 Copy', 2000);
    }});
}}
</script>

</body>
</html>"""


def cards_by_status(jobs, status):
    result = []
    for i, job in enumerate(jobs):
        if job.get("status") == status:
            badge_html, card_bg = status_badge(status)
            score = job.get("score", "?")
            sc = score_color(score) if isinstance(score, int) else "#888"
            found = job.get("found_at", "")[:10] if job.get("found_at") else "Unknown"
            hm = job.get("hiring_manager", "")
            job_num = i + 1
            result.append(f"""
        <div style="background:{card_bg};border:1px solid #333;border-radius:10px;padding:20px 24px;margin-bottom:16px;">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:10px;">
                <div>
                    <div style="font-size:18px;font-weight:bold;color:#fff;margin-bottom:4px;">{job.get('title','Unknown')}</div>
                    <div style="font-size:14px;color:#aaa;margin-bottom:8px;">{job.get('company','')} &nbsp;·&nbsp; {job.get('location','')}</div>
                    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
                        {badge_html}
                        <span style="color:{sc};font-size:13px;font-weight:bold;">★ {score}/10</span>
                        <span style="color:#666;font-size:12px;">Found {found}</span>
                    </div>
                </div>
                <a href="{job.get('link','#')}" target="_blank" style="background:#333;color:#fff;padding:8px 16px;border-radius:6px;text-decoration:none;font-size:12px;white-space:nowrap;">View Job ↗</a>
            </div>
            <div style="margin-top:12px;color:#bbb;font-size:13px;font-style:italic;">{job.get('reason','')}</div>
            {"<div style='margin-top:8px;font-size:12px;color:#888;'>Contact: " + hm + "</div>" if hm else ""}
            <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap;">
                <button onclick="toggleCL({job_num})" style="background:#1a2a3a;color:#7ec8e3;border:1px solid #2a4a6a;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;">📄 Cover Letter</button>
            </div>
            <div id="cl-{job_num}" style="display:none;margin-top:16px;background:#0d0d1a;border:1px solid #222;border-radius:6px;padding:16px;">
                <pre style="font-family:'Georgia',serif;font-size:13px;line-height:1.7;color:#ccc;white-space:pre-wrap;margin:0;">{job.get('cover_letter','Not generated yet.')}</pre>
                <button onclick="copyText({job_num})" style="margin-top:12px;background:#2a2a3a;color:#aaa;border:1px solid #444;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;">📋 Copy</button>
            </div>
        </div>""")
    return result

def cards_by_status_html(jobs, status):
    return cards_by_status(jobs, status)


def main():
    jobs = load_jobs()
    if not jobs:
        print("No jobs found in ares_pending.json")
        return

    html = build_html(jobs)
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, prefix='bear_tracker_')
    tmp.write(html)
    tmp.close()

    print(f"Opening tracker with {len(jobs)} jobs...")
    webbrowser.open(f"file://{tmp.name}")
    print(f"File: {tmp.name}")

if __name__ == "__main__":
    main()
