# Where we are (Nov 12, 2026)

Plain-English save point for Blaze. Read this first next time.

## Right now
- **The old ARES is still running** on the always-on Mac, same as this morning
  (Slack / Goose, YES / NO / CL). Nothing live changed.
- **The new ARES is finished code**, saved on GitHub on the branch
  `chore/requirements-and-models`. It isn't running anywhere yet.
- **It's waiting on one thing: Twilio**, the service that lets ARES text your
  real phone number.

## What we did today, in order
1. **Got the ARES code onto the MacBook** so we code here and the always-on Mac
   runs it ("code here, run there").
2. **Updated the AI models** to the newest Claude versions and added a list of
   everything ARES needs installed (`requirements.txt`).
3. **Split ARES from your pilots.** Maverick, Goose, Bob and Rooster are just
   your personal fun stack now. Goose has no job duties.
4. **Took ARES off Slack** (a future employer's Slack can't be used, and Discord
   is out). ARES will text you instead.
5. **Made ARES chattable.** Text it normally ("which job is best?") and it
   answers. Also: text **SCAN** to run a job search on demand.
6. **Added LinkedIn.** Each job alert shows people you know at that company and
   a link to your friends-of-friends there.
7. **Picked how ARES texts you.** We tried Telegram (no), then iMessage (needed
   a second Apple ID, too annoying), and settled on **Twilio**: real texts to
   your real number. The Twilio code is built and tested.
8. **Logged this MacBook into GitHub** and uploaded everything.
9. **Wrote down every idea** in [ROADMAP.md](ROADMAP.md) so nothing gets lost.

## Next steps (one at a time)
0. **If you haven't yet:** on the always-on Mac, tell its Claude:
   `git checkout main in ~/ares. Don't restart anything.`
   This keeps the old ARES safe while we wait.
1. **Sign up for Twilio** at twilio.com (about 10 min).
2. **Buy a Twilio phone number** (about $1–2/month).
3. **Fill out Twilio's texting registration** (called "A2P 10DLC", pick
   *Sole Proprietor*). Then wait a few days for approval.
4. **When approved:** put the Twilio keys on the always-on Mac, send a test
   text, restart ARES. **ARES is live** (about 5 min).
5. **Download your LinkedIn connections** (LinkedIn → Settings → Data privacy →
   Get a copy of your data → Connections) so ARES knows who you know.

## How you'll use ARES once it's live
You get a morning text with today's best jobs and who you know at each one.
Text back:
- **YES**: apply to the next job
- **NO**: skip it
- **CL**: see the cover letter
- **SCAN**: search for jobs right now
- or just ask anything in normal words.

## Later (in ROADMAP.md)
A dashboard you can log into from anywhere, running on Anthropic's hosted
agents, and maybe turning ARES into a business.
