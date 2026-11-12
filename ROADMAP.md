# A.R.E.S. Roadmap

Every idea Blaze has raised, so nothing gets lost. Newest decisions at the top
of each section. Move items to **Done** with the date when they ship.

## Goal for now
Get applications out. A.R.E.S. works on its own, separate from the personal
pilot stack.

## Decisions
- **2026-11-12:** Skipped the iMessage bridge (it needed a second Apple ID).
  The old Slack A.R.E.S. keeps running until Twilio is approved; then deploy.
  `imessage.py` stays in the repo as an option.
- **2026-11-12:** Texting goes through **Twilio** (a real phone number texting
  Blaze's phone). No Telegram. Twilio needs US carrier registration (A2P 10DLC)
  first, which takes days to a couple of weeks.
- **2026-11-12:** A.R.E.S. is its own system. The personal Slack pilots
  (Maverick, Goose, Bob, Rooster) are a personal fun stack and have **no**
  A.R.E.S. duties. Goose keeps his identity but no responsibilities for now.
- **2026-11-12:** No Slack or Discord for A.R.E.S. A future employer's Slack
  can't be used, and Discord banned the account. A.R.E.S. talks to Blaze by
  text (Twilio SMS) and later through its own dashboard.
- **2026-11-12:** Workflow: code on the MacBook, push to GitHub, and the
  always-on Mac pulls and runs it.

## Now (today)
- [x] Add requirements.txt and move to Claude 5.5 models
- [x] A.R.E.S. texts Blaze directly for briefs, approvals and chat (built on
      Telegram; switching to Twilio SMS)
- [x] Twilio SMS code: send + receive replies (`twilio_sms.py`)
- [ ] Twilio: create account, buy number, submit A2P 10DLC registration
- [ ] When approved: Twilio keys in .env on the always-on Mac,
      `python3 twilio_sms.py test`, restart A.R.E.S.
- [x] Normal-chat conversation with A.R.E.S. (Claude directly, not OpenClaw)
- [x] Text SCAN to run a scan on demand
- [x] Goose takes no A.R.E.S. commands in Slack
- [x] LinkedIn: flag 1st-degree connections at each company (from Blaze's
      LinkedIn connections export)
- [x] LinkedIn: one-tap link to the 2nd-degree people at each company, and
      who the mutual connection is
- [ ] Deploy to the always-on Mac and run a live test scan
- [ ] Download the LinkedIn connections export and drop it in the folder
- [ ] Chat can take actions ("apply to #2", "rewrite that letter"), not just
      tell Blaze which command to text
- [ ] Rewrite the older sections of TUTORIAL.md for the split (a note at the
      top covers it for now)

## Next
- [ ] Web dashboard you can log into from anywhere (phone home screen too):
      pending jobs, Approve / Skip / Edit cover letter, and a chat panel
- [ ] Move A.R.E.S. to a fresh repo built as a product, not a personal script
- [ ] Experiment: run A.R.E.S. on Anthropic Managed Agents (hosted agent loop
      + sandbox + scheduled 7am runs + vault for secrets). First check whether
      Playwright can fill a Greenhouse form inside its sandbox.
- [ ] Memory: A.R.E.S. remembers preferences across chats ("never defense")
- [ ] Stronger model (Sonnet 5.5) for scoring and cover letters, Haiku for
      quick form answers
- [ ] Run in the cloud instead of on a home Mac, with crash alerts

## Later (business)
- [ ] Multi-user: per-user profile, resume and preferences instead of values
      written into `ares.py`
- [ ] Check job-board terms of service before auto-applying on customers' behalf
- [ ] Billing, onboarding

## Done
- 2026-11-12: A.R.E.S. split from the pilots (Telegram texting, normal chat,
  SCAN command, LinkedIn 1st/2nd-degree network in every brief)
- 2026-11-12: requirements.txt; Claude 5.5 model IDs; thinking disabled on
  Haiku 5.5 calls
