# A.R.E.S. — Project History & Evolution

> Why the code looks the way it does. If you're a Claude trying to understand a
> weird name, a dead code path, or a seam that doesn't quite line up, the answer
> is usually historical — it's here. Read alongside [TUTORIAL.md](TUTORIAL.md).

---

## The arc, in one sentence

A single Telegram bot that said YES/NO to jobs → a four-persona Slack fleet
wired into a personal AI operating system (OpenClaw), built by someone with
**zero prior coding background**.

---

## Timeline

### Early May 2026 — The Telegram era (v0)
A.R.E.S. started as **one Telegram bot, one channel**. The loop was minimal:
scan job boards → score → ping Telegram → reply `YES`/`NO` to approve or skip an
application. The goal was just to get the scanner + AI-scoring loop stable and
trustworthy before investing in a richer interface.

Artifacts from this era still in the tree:
- `poll_telegram()`, `send_telegram()`, `download_telegram_file()` in `ares.py`
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` env vars
- `ares.py.bak` (May 6) — the oldest surviving backup, ~40 KB, roughly the
  Telegram-era scanner before the Slack/OpenClaw rebuild more than doubled it.

### Mid May 2026 — The rebuild: Slack + OpenClaw
Once the scan loop was solid, the **surface** was rebuilt from scratch. Telegram
was swapped for **four specialized Slack bots**, each routed through the
**OpenClaw** gateway with its own persona, shell allowlist, and domain. This is
the single biggest architectural shift in the project's life — it's why `ares.py`
jumped from ~40 KB to ~90 KB and why `slack_pilots.py` exists at all.

The `.bak` files bracket this rebuild almost day by day:
- `ares.py.bak_grizz_fix` (May 12) — a fix to the then-"Grizz" bot wiring
- `ares.py.bak_jarvis` (May 12) — an intermediate naming pass
- `ares.py.bak_openclaw_forward` (May 13) — the point where freeform messages
  started being **forwarded into OpenClaw** (`forward_to_openclaw()`), rather
  than handled locally. This is the birth of the "A.R.E.S. is an organ of
  OpenClaw" model.

### 2026-05-15 — Telegram goes dark; pilots get their callsigns
Two changes landed together:
- **Telegram polling disabled by default.** Slack became the one live surface.
  Telegram was left behind the `ARES_ENABLE_TELEGRAM=1` flag rather than
  deleted — still supported, just off. (See the comment at `ares.py`'s
  `__main__` block.)
- **The pilots got their current callsigns.** The `SYSTEM_PROMPTS` keys and the
  pilot→agent mapping were updated to **Maverick / Goose / Bob / Rooster**.

### Why the env vars don't match the pilot names
This is the project's most confusing fossil. The bots were originally named
**Grizz / Ice Bear / Panda / Tabes** (the We Bare Bears + a fourth). When they
were re-christened with aviation callsigns, the **`.env` variable names were
deliberately left alone** so existing `.env` files kept working without a
migration. The result is the permanent mapping:

| Env var (legacy) | Pilot (current) | OpenClaw agent |
|---|---|---|
| `SLACK_TOKEN_GRIZZ` | Maverick | `main` |
| `SLACK_TOKEN_ICE_BEAR` | Goose | `ice-bear` |
| `SLACK_TOKEN_PANDA` | Bob | `panda` |
| `SLACK_TOKEN_TABES` | Rooster | `ranger-tabes` |

Note the OpenClaw agent ids kept the **old animal names** (`ice-bear`, `panda`,
`ranger-tabes`) while the Slack personas moved to callsigns. Both naming layers
survive. This is expected, not a bug.

### Mid July 2026 — Documentation & packaging pass
`README.md`, `.env.example`, and the comprehensive `.gitignore` were brought to
their current state. The repo became presentable — this is the version that went
to GitHub as the first real commit.

### 2026-08-30 — Warm-connection matching
`linkedin_match.py` added: find warm LinkedIn connections at target companies
from **public DuckDuckGo snippets** (no API keys, cached 7 days). `enrich_job()`
in the scanner now attaches match candidates to high-scoring roles so outreach
can suggest a real human instead of a generic hiring-manager address.

### 2026-10-24 — Published to GitHub
The codebase was pushed to `github.com/blazerenezeder/A.R.E.S`. First commit
captured the stable July system; the second added the LinkedIn matcher and wired
it into the Slack outreach flow. The runtime LinkedIn cache was gitignored at
this point (it regenerates itself; versioning it is pointless and leaks search
patterns).

---

## Design decisions worth remembering

- **No web framework.** Deliberately a long-running daemon + `requests` +
  Playwright. Easy to reason about, easy for launchd to babysit, nothing to
  keep patched.
- **OpenClaw owns the personas, not this repo.** Voice/allowlist/identity live
  in each agent's OpenClaw workspace. `slack_pilots.py` is plumbing. The
  `SYSTEM_PROMPTS` dict is intentionally empty dead code (kept only so the
  history-dict keys exist). Don't look for a pilot's personality in this repo —
  it isn't here.
- **State is flat JSON, gitignored.** `ares_seen.json` (dedupe) and
  `ares_pending.json` (the live pipeline) are the whole database. Simple,
  inspectable, never committed.
- **Humans stay in the loop.** The scanner never applies unattended — it posts a
  brief and waits for a YES. The natural-language YES/NO/CL synonym sets exist
  because Blaze approves jobs in his own voice ("send it", "scrub that one"),
  not with rigid commands.
- **Telegram wasn't deleted, it was demoted.** A recurring theme: old surfaces
  get flagged off, not ripped out, so the system degrades gracefully if the new
  surface has a bad day.

---

## The recurring failure mode (institutional memory)

A.R.E.S.'s most common production breakage is **not** a bug in this repo. It's an
**upstream OpenClaw change** — a version bump or a Control-UI edit — that breaks
the pilot integration at the seam. When "it was working yesterday," check
OpenClaw and the pilots' workspaces **before** you start editing `ares.py`. And
remember: a `"<pilot> unreachable"` message is far more often **queue contention
while that pilot is busy** than an actual outage. Root-cause from the logs; find
the change point; resist patching symptoms.
