# A.R.E.S. — Autonomous Role Extraction System

A self-hosted job hunting agent that runs 24/7, finds relevant roles, scores them with AI, drafts cover letters, and applies through the browser — controlled entirely from Slack.

## Architecture

A.R.E.S. is wired into a personal AI operating system called **OpenClaw**, and surfaces to me through four specialized Slack agents I call the pilots:

| Pilot | OpenClaw agent | Domain |
|---|---|---|
| **Maverick** | `main` | Coordination, synthesis, cross-domain routing |
| **Goose** | `ice-bear` | A.R.E.S. — job scans, scoring, cover letters, auto-apply |
| **Bob** | `panda` | Creative — Gumroad product copy, LinkedIn, brand voice |
| **Rooster** | `ranger-tabes` | Income & outdoors — surf reports, revenue tracking, sales |

Every Slack DM goes through the OpenClaw gateway, gets routed to the right agent, executes tool calls against my Mac's real filesystem (with per-agent shell allowlists), and posts back to Slack. `slack_pilots.py` is the Socket Mode process that keeps the four bots live and translates Slack messages into `openclaw agent` calls.

## What A.R.E.S. Does

Every morning at 7am:

- Scrapes **Greenhouse, Lever, Ashby, and target company career pages** for new roles
- Also pulls from **Indeed** (HTML + RSS) as a supplement
- Filters by Bay Area geo, salary floor, and an exclusion keyword list
- Scores each role 1–10 with Claude Sonnet 4.6 via OpenClaw — combining fit and realistic odds of getting past the ATS
- Enriches high-scoring leads with hiring manager contact info via **Hunter.io**
- Looks up company registered addresses via the **California Secretary of State**
- Generates a tailored cover letter in my voice, per role
- Posts the daily brief to `#ares-pipeline` in Slack, and pings Goose for review

On approval:

- **Greenhouse and Ashby applications** — auto-filled and submitted via a **Playwright** browser session
- Other job boards — link opens in browser for manual submission
- All state persisted in `ares_pending.json` and `ares_seen.json`

Live control:

- DM Goose in Slack to check pipeline state, trigger scans, or force-apply a role
- Approve or skip roles inline; Goose executes and reports back

## Tech Stack

- Python 3 (no framework — long-running daemon + Playwright + requests)
- Anthropic Claude (via OpenClaw's gateway; Claude Sonnet 4.6 for scoring, Claude Haiku 4.5 for lighter tasks)
- Slack Socket Mode (`slack_sdk`) for the four pilot bots
- Playwright for browser automation (Greenhouse + Ashby form auto-fill)
- BeautifulSoup + requests for scraping
- Hunter.io, CA Secretary of State APIs for enrichment
- launchd for daemonization on macOS

## Origins

Started as a single Telegram bot in early May 2026 — one channel, one bot, YES/NO commands to approve job applications. Once the scanner + AI scoring loop was stable, I rebuilt the surface: swapped Telegram for four specialized Slack agents routed through OpenClaw, each with its own persona, shell allowlist, and domain. Telegram is still supported (behind a feature flag) but Slack + OpenClaw is the primary interface.

## Setup

1. Clone the repo
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in your credentials (Anthropic, Slack, Hunter, etc.)
4. Edit the `CANDIDATE` and `CANDIDATE_PROFILE` blocks in `ares.py` to match your background
5. Edit `CAREER_PAGES`, `ASHBY_SEARCHES`, and `EXCLUDE_KEYWORDS` for your target roles
6. Install Playwright browsers: `playwright install chromium`
7. Run: `python3 ares.py` (or set up the launchd plist for 24/7 operation)

## Customization

- `CAREER_PAGES` — target Greenhouse company slugs
- `ASHBY_SEARCHES` — Ashby search URLs
- `EXCLUDE_KEYWORDS` — auto-filter list
- `CANDIDATE_PROFILE` — feed the cover letter generator
- `generate_cover_letter()` — prompt template for voice matching

## Files

- `ares.py` — the daemon: scanning, scoring, cover letters, Playwright apply, Slack posting
- `slack_pilots.py` — Socket Mode process managing the four pilot bots + OpenClaw routing
- `tracker.py` — application submission tracking
- `apply_now.py` — one-shot Playwright runner for approved roles

## Status

Currently running in production on my Mac as two launchd services (`com.icebear.ares_daemon`, `com.icebear.slack_pilots`), watched over by OpenClaw. No formal coding background — built from scratch, iterated in the open.
