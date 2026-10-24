# A.R.E.S. — Onboarding Tutorial for Claude

> You're a coding agent that just landed in the `~/ares` repo. This is your
> fast-start guide. Read it before touching anything. It assumes you know
> Python but know **nothing** about this project's conventions, its landmines,
> or how it connects to the wider system. Those are what get you.

---

## 1. What this repo is, in one breath

A.R.E.S. (Autonomous Role Extraction System) is a self-hosted, always-on job
hunting agent for one person (Blaze). It scans job boards every morning, scores
roles with Claude, writes tailored cover letters, auto-applies through a real
browser, and is driven entirely from Slack. It is **production-critical** — it
runs live against real job applications. Breaking it has real-world cost.

It is **not** a standalone app. It is one organ inside a larger personal AI OS
called **OpenClaw**. Keep that in your head the whole time; most of the
confusing parts of this codebase are the seams where A.R.E.S. meets OpenClaw.

---

## 2. The mental model (read this twice)

There are **two long-running processes**, and they are easy to confuse:

| Process | File | Role |
|---|---|---|
| **The scanner** | `ares.py` | Finds/scores/enriches jobs, generates cover letters, auto-applies. Runs the daily scan. |
| **The Slack backend** | `slack_pilots.py` | Keeps four Slack bots ("pilots") live, routes every DM into OpenClaw, and handles YES/NO/CL job commands by calling into `ares.py`. |

`slack_pilots.py` imports `ares.py` as a module (`import ares as _ares`) to reuse
its job-command logic. So the Slack process has the scanner's code loaded, but
the *scheduled scan* is the scanner's own `daily_run()`.

**The four pilots.** Blaze talks to four Slack bots, each a persona backed by a
different OpenClaw agent:

| Pilot | OpenClaw agent id | Domain |
|---|---|---|
| **Maverick** | `main` | Coordination / routing. **Coordinates only — he is NOT a relay.** |
| **Goose** | `ice-bear` | A.R.E.S. itself — job scans, scoring, apply |
| **Bob** | `panda` | Creative / brand / copy |
| **Rooster** | `ranger-tabes` | Income & outdoors / revenue |

This mapping lives in `slack_pilots.py:PILOT_TO_AGENT`. Blaze DMs each pilot
**directly** — Maverick is not a middleman you route everything through.

**How a Slack message becomes a reply:** `claude_reply()` shells out to the
OpenClaw CLI — `openclaw agent --agent <id> --message <text> --json` — and
parses the JSON. The actual persona (voice, allowlist) lives in that agent's
OpenClaw workspace (`SOUL.md` / `IDENTITY.md`), **not** in this repo. The
`SYSTEM_PROMPTS` dict in `slack_pilots.py` is **dead code** kept only so the
history-dict keys exist. Don't try to edit a pilot's personality here; it isn't
here.

---

## 3. ⚠️ The landmines (the stuff that will bite you)

**3.1 — Env var names are LEGACY callsigns, not the current pilots.**
The project started with different bot names. The `.env` keys were never
renamed, so:

```
SLACK_TOKEN_GRIZZ     → Maverick
SLACK_TOKEN_ICE_BEAR  → Goose
SLACK_TOKEN_PANDA     → Bob
SLACK_TOKEN_TABES     → Rooster
```

If you see `SLACK_TOKEN_GRIZZ` posting to `#ares-pipeline`, that is **Maverick's
token doing scanner notifications** — correct, not a bug. Do not "fix" the
names.

**3.2 — `"<pilot> unreachable"` is usually NOT breakage.**
When `claude_reply()` / `forward_to_openclaw()` returns `"[Goose unreachable…]"`,
the first instinct is "the integration is broken." Most of the time it's just
**queue contention** — the pilot was busy with another task and the `openclaw`
call timed out (150s). Check whether the agent was simply busy before you start
surgery on the JSON parser.

**3.3 — "It was working yesterday" → find the change point first.**
When something regresses, do **not** patch the symptom. Go to the logs, find the
moment behavior changed, and root-cause from there. The most common real cause
of A.R.E.S. breakage is an **OpenClaw update or a Control-UI change** upstream
that breaks the pilot integration — not a bug in this repo. Look there early.

**3.4 — Telegram is legacy but still in the code.**
A.R.E.S. was born as a Telegram bot. That code still exists (`poll_telegram`,
`send_telegram`, `download_telegram_file`) but is **off by default**. It only
runs if `ARES_ENABLE_TELEGRAM=1`. Slack is the primary and only live surface.
Don't delete the Telegram paths casually, but don't assume they're active either.

**3.5 — Runtime/state files are NOT in git, and some contain PII.**
`ares_pending.json`, `ares_seen.json`, `ares.log`, `slack_pilots_history.json`,
`slack_pilots.log`, `linkedin_match_cache.json`, and all `*.bak*` files are
gitignored on purpose. The history/log files contain personal data. **Never
commit them, never paste their contents into anything external.**

**3.6 — Out-of-scope scripts live in the dir but aren't A.R.E.S.**
`security_scan.py`, `muon_apply.py`, `debug_form.py` are gitignored one-offs.
They are not part of the system. Don't wire them in or document them as if they
are.

---

## 4. The daily scan pipeline (what `ares.py` actually does)

Entry: `daily_run()` → `_daily_run_inner()`. The flow:

1. `load_seen()` — set of job IDs already processed (`ares_seen.json`)
2. `fetch_all_jobs()` — scrapes **Greenhouse, Lever, Ashby, target career
   pages**, plus **Indeed** (HTML + RSS) as a supplement
3. Drop anything already in `seen`; add everything new to `seen` and save
4. `basic_filter()` — Bay Area geo, salary floor, exclusion keywords,
   experience ceiling (`_exceeds_experience`)
5. `ai_score_jobs()` — Claude scores each 1–10 on fit **and** realistic odds of
   clearing the ATS; threshold-gated
6. Take the **top 4**, then per job:
   - `enrich_job()` — hiring-manager contact (Hunter.io), company registered
     address (CA Secretary of State), and warm LinkedIn connections
     (`linkedin_match.py`)
   - `generate_cover_letter()` — tailored, in Blaze's voice
   - append to `ares_pending.json` with `status: "pending"`
7. Post the daily brief to Slack `#ares-pipeline` + `#morning-brief` (via the
   `SLACK_TOKEN_GRIZZ` = Maverick token), ending with
   `YES → apply next | NO → skip | CL → cover letter`

**Approval loop:** Blaze replies to Goose in Slack. `handle_command()` in
`ares.py` normalizes a huge set of natural-language synonyms
(`_PILOT_YES` / `_PILOT_NO` / `_PILOT_CL` — "send it", "cleared hot", "scrub",
etc.) into YES/NO/CL. YES triggers the browser apply:

- **Greenhouse** (`greenhouse_apply`) and **Ashby** (`ashby_apply`) —
  Playwright fills and submits the form (`fill_by_label`, human-typed input,
  canned + AI-generated answers to screener questions)
- Everything else — opens the link for manual submission

---

## 5. Running & operating it

```bash
# one-shot scan (does a full daily_run and exits)
python3 ares.py

# daemon mode (idle loop; Telegram polling only if ARES_ENABLE_TELEGRAM=1)
python3 ares.py --daemon

# the Slack pilots backend (Socket Mode, real-time)
python3 slack_pilots.py

# local HTML pipeline dashboard
python3 tracker.py        # builds HTML from ares_pending.json
python3 apply_now.py      # quick "what's pending" view
```

In production these are **launchd-managed** on Blaze's Mac — they come back on
crash/reboot. If you change startup behavior, remember launchd owns the lifecycle,
not a terminal you're sitting in.

Config is `.env` (never committed). `.env.example` is the authoritative list of
every variable. Copy → fill → run.

---

## 6. Common tasks & where to go

| You want to… | Go to |
|---|---|
| Add/adjust a job source | `fetch_*` functions + `fetch_all_jobs()` in `ares.py` |
| Change filtering rules | `basic_filter`, `is_bay_area`, `salary_ok`, `_exceeds_experience` |
| Tune scoring | `ai_score_jobs` (prompt + threshold) |
| Change cover-letter voice | `generate_cover_letter` |
| Fix a broken auto-apply form | `greenhouse_apply` / `ashby_apply` (Playwright selectors) |
| Add a screener-answer | `pick_canned` / `ai_answer` (and the static `_*_static` variants) |
| Warm-connection lookup | `linkedin_match.py` (`find_matches_for_company`, `enrich_job`) |
| Slack routing / pilots | `slack_pilots.py` (`PILOT_TO_AGENT`, `claude_reply`, `_process_message`) |

---

## 7. Debugging playbook

1. **Reproduce via logs, not guesses.** `ares.log` and `slack_pilots.log` are
   the ground truth. `slack_pilots.log` is huge — `tail`/`grep` it, don't open it.
2. **Find the change point.** Grep the log for the first timestamp where the
   behavior changed. "Was working" means something changed — find *what*.
3. **Rule out upstream.** Did OpenClaw update? Did a pilot's workspace change?
   Those break A.R.E.S. before A.R.E.S.'s own code does.
4. **Check for queue contention** before declaring the integration dead (see 3.2).
5. **Only then** edit code — and prefer the smallest change that addresses the
   root cause, not the symptom.

---

## 8. Etiquette for working here

- Match the surrounding code style — plain stdlib-flavored Python, no framework.
- Don't commit secrets, logs, state, caches, or PII. If unsure, it's probably
  gitignored for a reason — check `.gitignore` first.
- Prefer small, reversible commits. This is production; a bad push has
  real-world consequences for someone's job search.
- When you fix something non-obvious, consider whether it belongs in this
  tutorial or in [HISTORY.md](HISTORY.md) so the next Claude doesn't relearn it
  the hard way.

Welcome to the flight deck. Fly safe.
