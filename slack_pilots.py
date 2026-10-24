#!/usr/bin/env python3
"""
slack_pilots.py — Four-pilot Slack bot backend for OpenClaw workspace.
Uses Socket Mode for real-time DM responses (no polling delay).

Maverick / Goose / Bob / Rooster each listen for DMs from Blaze
and respond in character using Claude claude-sonnet-4-6.
"""

import os
import sys
import re
import json
import time
import logging
import threading
import subprocess
import requests
from datetime import datetime

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.errors import SlackApiError
from anthropic import Anthropic

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# Import ares for job command handling (YES/NO/CL)
sys.path.insert(0, os.path.dirname(__file__))
import ares as _ares

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
BLAZE_SLACK_ID    = os.getenv("BLAZE_SLACK_ID", "U0B29SRFNBV")
FLIGHT_DECK_NAME  = os.getenv("FLIGHT_DECK_CHANNEL", "flight-deck")
ARES_PIPELINE_NAME = os.getenv("ARES_PIPELINE_CHANNEL", "ares-pipeline")
STATE_FILE        = "/tmp/slack_pilots_state.json"
HISTORY_FILE      = os.path.join(os.path.dirname(__file__), "slack_pilots_history.json")
LOG_FILE          = os.path.join(os.path.dirname(__file__), "slack_pilots.log")
MODEL             = "claude-sonnet-4-6"
HISTORY_LIMIT     = 20  # pairs kept per pilot

log = logging.getLogger("slack_pilots")
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s")
    fh = logging.FileHandler(LOG_FILE)
    fh.setFormatter(fmt)
    log.addHandler(fh)
    log.propagate = False

BLAZE_CONTEXT = """
Blaze Renezeder. 24. San Francisco. Operations professional with a builder mindset.
Background: Universal Banker (million-dollar transactions, zero errors), GTM/Ops at Beer Girl
(startup, 300-mile keg delivery routes, ran events), M&A Sourcing at Rejigg, Event Coordinator
at Wagon Wheel Brewing (100+ events), Operations Lead at Coast Film Festival (2500-person event,
zero queue delays). Built A.R.E.S. (Autonomous Role Extraction System) and OpenClaw (personal AI OS)
with zero prior coding background. Eagle Scout. Black Belt Taekwondo. Student Pilot.
Target: Ops Coordinator, Chief of Staff, BizOps, Program Manager at frontier tech (robotics,
aerospace, space, AV). Bay Area only. No defense/weapons/surveillance.
"""

# NOTE: SYSTEM_PROMPTS is now dead code — claude_reply() routes via `openclaw agent`
# and the actual personas live in each pilot's workspace SOUL.md/IDENTITY.md.
# This dict is kept only because history_locks and _load_histories iterate its keys.
# Keys updated to pilot callsigns 2026-05-15.
SYSTEM_PROMPTS = {
    "Maverick": "",
    "Goose": "",
    "Bob": "",
    "Rooster": "",
}

state_lock = threading.Lock()
history_locks  = {name: threading.Lock() for name in SYSTEM_PROMPTS}

def _load_histories() -> dict:
    try:
        with open(HISTORY_FILE) as f:
            data = json.load(f)
        # Ensure all pilot keys exist
        return {name: data.get(name, []) for name in SYSTEM_PROMPTS}
    except Exception:
        return {name: [] for name in SYSTEM_PROMPTS}

def _save_histories(histories: dict):
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(histories, f, indent=2)
    except Exception as e:
        log.warning(f"Failed to save history: {e}")

conv_histories = _load_histories()
log.info(f"Loaded histories: { {k: len(v) for k, v in conv_histories.items()} }")


def get_ares_status() -> str:
    pending_file = os.path.join(os.path.dirname(__file__), "ares_pending.json")
    try:
        with open(pending_file) as f:
            jobs = json.load(f)
        pending  = [j for j in jobs if j.get("status") == "pending"]
        approved = [j for j in jobs if j.get("status") == "approved"]
        skipped  = [j for j in jobs if j.get("status") == "skipped"]
        lines = [f"A.R.E.S. Pipeline: {len(pending)} pending | {len(approved)} approved | {len(skipped)} skipped"]
        for i, job in enumerate(pending[:5], 1):
            lines.append(f"  #{i} {job.get('title')} @ {job.get('company')} | Score {job.get('score')}/10 | {job.get('location')}")
        return "\n".join(lines)
    except Exception as e:
        return f"A.R.E.S. status unavailable: {e}"


def get_surf_report() -> str:
    try:
        sys.path.insert(0, "/Users/icebear/tabes")
        from surf import surf_report
        return surf_report()
    except Exception as e:
        return f"Surf report unavailable: {e}"


PILOT_TO_AGENT = {
    "Maverick": "main",
    "Goose": "ice-bear",
    "Bob": "panda",
    "Rooster": "ranger-tabes",
}


def claude_reply(bot_name: str, user_text: str) -> str:
    agent_id = PILOT_TO_AGENT.get(bot_name)
    if not agent_id:
        return f"[{bot_name} is unknown to OpenClaw]"
    message = (user_text or "").strip()
    if not message:
        return ""
    try:
        result = subprocess.run(
            ["openclaw", "agent", "--agent", agent_id,
             "--message", message, "--json", "--timeout", "120"],
            capture_output=True, text=True, timeout=150,
        )
    except subprocess.TimeoutExpired:
        log.warning(f"[{bot_name}] openclaw agent timed out")
        return f"[{bot_name} is taking too long — try again]"
    except FileNotFoundError:
        log.warning(f"[{bot_name}] openclaw CLI not found on PATH")
        return f"[{bot_name} offline: openclaw CLI missing]"
    except Exception as e:
        log.error(f"[{bot_name}] openclaw call failed: {e}")
        return f"[{bot_name} call failed: {e}]"

    stdout = result.stdout or ""
    brace = stdout.find("{")
    if brace < 0:
        err = ""
        raw = (result.stderr or stdout).strip()
        if raw:
            err = raw.splitlines()[0]
        log.warning(f"[{bot_name}] no JSON (exit {result.returncode}): {(result.stderr or stdout)[:200]}")
        return f"[{bot_name} unreachable: {err[:200]}]" if err else f"[{bot_name} unreachable (no output)]"
    try:
        data = json.loads(stdout[brace:])
    except json.JSONDecodeError as e:
        log.warning(f"[{bot_name}] JSON parse failed: {e}")
        return f"[{bot_name} response unreadable]"

    container = data.get("result") if isinstance(data.get("result"), dict) else data
    payloads = container.get("payloads") or []
    if isinstance(payloads, list) and payloads and isinstance(payloads[0], dict):
        text = payloads[0].get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    meta = container.get("meta") or {}
    text = meta.get("finalAssistantVisibleText")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return ""


POLL_INTERVAL = 2

def _find_channel_id(web: WebClient, name: str):
    cursor = None
    while True:
        try:
            r = web.conversations_list(
                exclude_archived=True,
                types="public_channel",
                limit=200,
                cursor=cursor,
            )
        except SlackApiError as e:
            log.warning(f"conversations_list failed for #{name}: {e}")
            return None
        for ch in r.get("channels", []):
            if ch.get("name") == name:
                return ch.get("id")
        cursor = (r.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            return None


def _poll_channel(web, bot_name, channel_id, last_ts, on_message):
    try:
        r = web.conversations_history(channel=channel_id, limit=10)
    except SlackApiError as e:
        log.warning(f"[{bot_name}] poll error on {channel_id}: {e}")
        return last_ts
    messages = sorted(r.get("messages", []), key=lambda m: float(m.get("ts", 0)))
    for msg in messages:
        ts = msg.get("ts", "0")
        if float(ts) <= float(last_ts):
            continue
        if msg.get("bot_id") or msg.get("subtype"):
            last_ts = ts
            continue
        if msg.get("user") != BLAZE_SLACK_ID:
            last_ts = ts
            continue
        try:
            on_message(msg)
        except Exception as e:
            log.error(f"[{bot_name}] handler error: {e}")
        last_ts = ts
    return last_ts


def run_bot(bot_name: str, bot_token: str, app_token: str):
    web = WebClient(token=bot_token)
    log.info(f"[{bot_name}] Starting (polling mode)...")

    # Resolve this bot's own user ID so we can detect @-mentions in channels
    bot_user_id = None
    try:
        bot_user_id = web.auth_test().get("user_id")
        log.info(f"[{bot_name}] user_id={bot_user_id}")
    except SlackApiError as e:
        log.error(f"[{bot_name}] auth_test failed: {e}")

    # Open DM channel with Blaze
    dm_channel = None
    while not dm_channel:
        try:
            r = web.conversations_open(users=[BLAZE_SLACK_ID])
            dm_channel = r["channel"]["id"]
            log.info(f"[{bot_name}] DM channel: {dm_channel}")
        except SlackApiError as e:
            log.error(f"[{bot_name}] conversations_open failed: {e} — retrying in 10s")
            time.sleep(10)

    # Locate #flight-deck (best-effort; bot must be invited to channel by user)
    flight_deck_id = _find_channel_id(web, FLIGHT_DECK_NAME)
    if flight_deck_id:
        log.info(f"[{bot_name}] #{FLIGHT_DECK_NAME}: {flight_deck_id}")
    else:
        log.info(f"[{bot_name}] #{FLIGHT_DECK_NAME} not found (invite the bot to the channel)")

    # Goose additionally watches #ares-pipeline as his A.R.E.S. control channel
    ares_pipeline_id = None
    if bot_name == "Goose":
        ares_pipeline_id = _find_channel_id(web, ARES_PIPELINE_NAME)
        if ares_pipeline_id:
            log.info(f"[{bot_name}] #{ARES_PIPELINE_NAME}: {ares_pipeline_id} (control channel)")
        else:
            log.info(f"[{bot_name}] #{ARES_PIPELINE_NAME} not found (invite Goose to the channel)")

    last_ts_dm = str(time.time())
    last_ts_fd = str(time.time())
    last_ts_ap = str(time.time())

    log.info(f"[{bot_name}] Polling every {POLL_INTERVAL}s...")

    mention_token = f"<@{bot_user_id}>" if bot_user_id else None
    mention_re = re.compile(r"<@[UW][A-Z0-9]+>")

    def handle_dm(msg):
        _process_message(web, bot_name, bot_token, dm_channel, msg, from_channel=False)

    def _channel_mention_handler(reply_channel_id, is_control):
        def h(msg):
            text = (msg.get("text") or "")
            is_direct = bool(mention_token and mention_token in text)
            # Wing-wide triggers: Slack's @channel/@here render as <!channel>/<!here>.
            is_wing = "<!channel>" in text or "<!here>" in text
            if not (is_direct or is_wing):
                return  # mention-only mode (no chatter response)
            cleaned = mention_re.sub("", text)
            cleaned = cleaned.replace("<!channel>", "").replace("<!here>", "").strip()
            m = dict(msg)
            m["text"] = cleaned
            _process_message(web, bot_name, bot_token, reply_channel_id, m,
                             from_channel=True, is_control_channel=is_control)
        return h

    handle_flight_deck = _channel_mention_handler(flight_deck_id, is_control=False) if flight_deck_id else None
    handle_ares_pipeline = _channel_mention_handler(ares_pipeline_id, is_control=True) if ares_pipeline_id else None

    while True:
        try:
            last_ts_dm = _poll_channel(web, bot_name, dm_channel, last_ts_dm, handle_dm)
            if handle_flight_deck:
                last_ts_fd = _poll_channel(web, bot_name, flight_deck_id, last_ts_fd, handle_flight_deck)
            if handle_ares_pipeline:
                last_ts_ap = _poll_channel(web, bot_name, ares_pipeline_id, last_ts_ap, handle_ares_pipeline)
        except Exception as e:
            log.error(f"[{bot_name}] Error: {e}")
            time.sleep(5)
        time.sleep(POLL_INTERVAL)


CHANNEL_CONTEXT_HINT = (
    "[Context: replying in #flight-deck (public channel). "
    "Status updates and conversation only — do NOT start applications, "
    "submit forms, or take destructive actions. For action commands, "
    "Blaze will DM you directly. Keep replies brief.]\n\n"
)

ARES_PIPELINE_HINT = (
    "[Context: replying in #ares-pipeline — your A.R.E.S. control channel. "
    "Actions ARE allowed here: scans, job approvals (YES/NO/CL), pipeline "
    "commands, application runs. Treat this like a DM for operational purposes. "
    "Keep replies focused on A.R.E.S. work.\n"
    "SLACK FORMATTING: Slack does NOT render markdown tables — pipes and dashes "
    "show up as literal characters and look janky. Never use table syntax "
    "(`|` `---`). For structured data, use numbered lists or bulleted lists. "
    "Example: for a job list, write:\n"
    "  1. Score 9 — Mission Operations Coordinator @ Nuro\n"
    "  2. Score 9 — Operations & Supply Chain @ Waymo\n"
    "Bold with *asterisks*, not **double** (Slack uses single asterisks). "
    "Code and inline paths in `backticks`. Keep it scannable in a chat UI.]\n\n"
)


def _process_message(web, bot_name, bot_token, channel, msg, from_channel=False, is_control_channel=False):
    text = (msg.get("text") or "").strip()
    files = msg.get("files") or []

    # Slack file uploads (PDF resumes, cover letters, etc.) → save to ~/ares/inbox/
    if files:
        inbox = os.path.join(os.path.dirname(os.path.abspath(__file__)), "inbox")
        os.makedirs(inbox, exist_ok=True)
        saved = []
        for f in files:
            url = f.get("url_private_download") or f.get("url_private")
            name = os.path.basename(f.get("name") or "upload.bin")
            if not url:
                continue
            try:
                resp = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {bot_token}"},
                    timeout=60,
                )
                resp.raise_for_status()
                dest = os.path.join(inbox, name)
                if os.path.exists(dest):
                    root, ext = os.path.splitext(name)
                    dest = os.path.join(inbox, f"{root}_{int(time.time())}{ext}")
                with open(dest, "wb") as fout:
                    fout.write(resp.content)
                saved.append(dest)
                log.info(f"[{bot_name}] saved file: {dest}")
            except Exception as e:
                log.error(f"[{bot_name}] file download failed for {name}: {e}")
        if saved:
            names = ", ".join(os.path.basename(p) for p in saved)
            try:
                web.chat_postMessage(channel=channel, text=f"Got file{'s' if len(saved) > 1 else ''}: {names}")
            except SlackApiError as e:
                log.error(f"[{bot_name}] post error: {e}")
            synth = f"[Blaze uploaded file{'s' if len(saved) > 1 else ''}: {names} at {saved[0]}]"
            if text:
                synth += f"\nCaption: {text}"
            reply = claude_reply(bot_name, synth)
            if reply:
                try:
                    web.chat_postMessage(channel=channel, text=reply)
                except SlackApiError as e:
                    log.error(f"[{bot_name}] post error: {e}")
        return

    if not text:
        return

    log.info(f"[{bot_name}] '{text[:80]}'")

    # Goose intercepts job approval commands (with pilot-speak via _ares._normalize_command).
    # Allowed from DMs OR from Goose's control channel (#ares-pipeline). #flight-deck stays conversation-only.
    canonical = _ares._normalize_command(text)
    treat_as_control = (not from_channel) or is_control_channel
    is_job_cmd = treat_as_control and bot_name == "Goose" and canonical is not None
    if is_job_cmd:
        pending = _ares.load_pending()
        changed, response = _ares.handle_command(text, pending)
        if changed:
            _ares.save_pending(pending)
        reply = response or "Goose is on it."
    else:
        if is_control_channel:
            agent_input = ARES_PIPELINE_HINT + text
        elif from_channel:
            agent_input = CHANNEL_CONTEXT_HINT + text
        else:
            agent_input = text
        reply = claude_reply(bot_name, agent_input)

    try:
        web.chat_postMessage(channel=channel, text=reply)
        log.info(f"[{bot_name}] → '{reply[:80]}'")
    except SlackApiError as e:
        log.error(f"[{bot_name}] Post error: {e}")


BOTS = [
    # (display_name, bot_token_env, app_token_env)
    # env vars kept as legacy names to avoid forcing a .env edit; only display names changed.
    ("Maverick", os.getenv("SLACK_TOKEN_GRIZZ",    ""), os.getenv("SLACK_APP_TOKEN_GRIZZ",    "")),
    ("Goose",    os.getenv("SLACK_TOKEN_ICE_BEAR", ""), os.getenv("SLACK_APP_TOKEN_ICE_BEAR", "")),
    ("Bob",      os.getenv("SLACK_TOKEN_PANDA",   ""), os.getenv("SLACK_APP_TOKEN_PANDA",   "")),
    ("Rooster",  os.getenv("SLACK_TOKEN_TABES",   ""), os.getenv("SLACK_APP_TOKEN_TABES",   "")),
]

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("Slack Pilots — Socket Mode — ONLINE")
    log.info(f"{datetime.now().isoformat()}")
    log.info("=" * 60)

    missing = [(n, "bot" if not bt else "app") for n, bt, at in BOTS
               for _ in [1] if not bt or not at]
    if missing:
        log.error(f"Missing tokens: {missing}")
        sys.exit(1)

    threads = []
    for bot_name, bot_token, app_token in BOTS:
        t = threading.Thread(
            target=run_bot,
            args=(bot_name, bot_token, app_token),
            name=f"pilot-{bot_name.lower().replace(' ', '-')}",
            daemon=True,
        )
        t.start()
        threads.append(t)
        log.info(f"[{bot_name}] Thread started")
        time.sleep(0.3)

    log.info("All 4 pilots live on Socket Mode.")

    try:
        while True:
            dead = [t.name for t in threads if not t.is_alive()]
            if dead:
                log.warning(f"Dead threads: {dead}")
            time.sleep(60)
    except KeyboardInterrupt:
        log.info("Shutting down.")
