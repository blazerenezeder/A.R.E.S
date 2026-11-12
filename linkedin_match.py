"""
linkedin_match.py — find warm LinkedIn connections at target companies via
public search-engine snippets. Attaches match candidates to jobs so the
Slack outreach flow can suggest a real human to message instead of a generic
hiring-manager address.

No API keys. Uses DuckDuckGo's HTML endpoint (which does not aggressively
rate-limit like Google) to parse public linkedin.com/in/ profile snippets.
Cached per (company, angle) for 7 days in ~/ares/linkedin_match_cache.json
to keep repeated scans cheap.

Match dimensions come from CANDIDATE_ANGLES. Ranking is heuristic: strongest
angles first (rare school + rare cred combos beat generic hobby matches).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote_plus, urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

log = logging.getLogger("linkedin_match")

CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "linkedin_match_cache.json")
CACHE_TTL_SECONDS = 7 * 24 * 3600
REQUEST_SLEEP = 3.0
PER_JOB_QUERY_CAP = 6
DDG_HTML_URL = "https://html.duckduckgo.com/html/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"


# Angles are ordered strongest-first. Weight = ranking score for the match.
# Query template uses {company} and {angle_terms} placeholders.
@dataclass
class Angle:
    label: str
    query_terms: list[str]
    weight: int


CANDIDATE_ANGLES: list[Angle] = [
    Angle("Chapman University alumnus",       ['"Chapman University"'],                        10),
    Angle("Chapman psychology alumnus",       ['"Chapman University"', '"psychology"'],         9),
    Angle("Chapman entrepreneurship alumnus", ['"Chapman"', '"entrepreneurship"'],              9),
    Angle("Rejigg alum",                      ['"Rejigg"'],                                     8),
    Angle("Partners Bank alum",               ['"Partners Bank of California"'],                8),
    Angle("Coast Film Festival alum",         ['"Coast Film Festival"'],                        8),
    Angle("Eagle Scout + student pilot",      ['"Eagle Scout"', '"student pilot"'],             8),
    Angle("Eagle Scout",                      ['"Eagle Scout"'],                                6),
    Angle("Student pilot / Piper Cherokee",   ['"student pilot"'],                              6),
    Angle("Taekwondo Black Belt",             ['"Taekwondo"', '"Black Belt"'],                  6),
    Angle("Volleyball",                       ['"volleyball"'],                                 4),
    Angle("Bay Area surfer",                  ['"surfing"', '"San Francisco"'],                 3),
]


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cache, f, indent=2)
    os.replace(tmp, CACHE_FILE)


def _cache_key(company: str, angle_label: str) -> str:
    return f"{company.lower().strip()}::{angle_label}"


def _cache_hit(cache: dict, key: str):
    entry = cache.get(key)
    if not entry:
        return None
    if time.time() - entry.get("cached_at", 0) > CACHE_TTL_SECONDS:
        return None
    return entry.get("results", [])


LINKEDIN_URL_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?")


def _ddg_search(query: str) -> list[dict]:
    """Return a list of {url, title, snippet} dicts from DuckDuckGo HTML."""
    try:
        resp = requests.post(
            DDG_HTML_URL,
            data={"q": query, "kl": "us-en"},
            headers={"User-Agent": UA, "Referer": "https://duckduckgo.com/"},
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        log.warning(f"DDG request failed for {query!r}: {e}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for res in soup.select("div.result"):
        a = res.select_one("a.result__a")
        snippet_el = res.select_one("a.result__snippet")
        if not a:
            continue
        raw_href = a.get("href", "")
        url = _unwrap_ddg_href(raw_href)
        if not url:
            continue
        results.append({
            "url": url,
            "title": a.get_text(" ", strip=True),
            "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else "",
        })
    return results


def _unwrap_ddg_href(href: str) -> Optional[str]:
    """DDG wraps outbound links in /l/?uddg=<encoded>."""
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        if "uddg" in qs:
            return qs["uddg"][0]
    return href


def _extract_linkedin_matches(results: list[dict]) -> list[dict]:
    matches = []
    for r in results:
        url = r["url"]
        if "linkedin.com/in/" not in url:
            continue
        m = LINKEDIN_URL_RE.search(url)
        if not m:
            continue
        clean_url = m.group(0).rstrip("/")
        name = _parse_name_from_title(r["title"])
        matches.append({
            "name": name,
            "linkedin": clean_url,
            "snippet": r["snippet"][:220],
        })
    return matches


def _parse_name_from_title(title: str) -> str:
    """LinkedIn titles come as 'Firstname Lastname - Role at Company | LinkedIn'."""
    if not title:
        return ""
    # Strip " | LinkedIn" tail
    title = re.sub(r"\s*\|\s*LinkedIn.*$", "", title, flags=re.IGNORECASE)
    # Take the part before ' - ' or ' – ' as the name
    for sep in (" - ", " – ", " — "):
        if sep in title:
            title = title.split(sep, 1)[0]
            break
    return title.strip()


def _search_company_angle(company: str, angle: Angle) -> list[dict]:
    terms = " ".join(angle.query_terms)
    query = f'site:linkedin.com/in/ "{company}" {terms}'
    log.info(f"query: {query}")
    raw = _ddg_search(query)
    matches = _extract_linkedin_matches(raw)
    time.sleep(REQUEST_SLEEP)
    return matches


def find_matches_for_company(company: str, max_matches: int = 3) -> list[dict]:
    """
    Run all angles against a company (with cache). Return top-ranked deduped
    match candidates, each annotated with the angle that surfaced them.
    """
    if not company:
        return []

    cache = _load_cache()
    per_url: dict[str, dict] = {}

    for angle in CANDIDATE_ANGLES[:PER_JOB_QUERY_CAP]:
        key = _cache_key(company, angle.label)
        cached = _cache_hit(cache, key)
        if cached is not None:
            angle_hits = cached
        else:
            try:
                angle_hits = _search_company_angle(company, angle)
            except Exception as e:
                log.warning(f"angle {angle.label!r} failed for {company!r}: {e}")
                angle_hits = []
            cache[key] = {"cached_at": time.time(), "results": angle_hits}

        for m in angle_hits:
            url = m["linkedin"]
            existing = per_url.get(url)
            entry = {
                "name": m["name"] or existing["name"] if existing else m["name"],
                "linkedin": url,
                "angle": angle.label,
                "weight": angle.weight,
                "snippet": m.get("snippet", "")[:180],
            }
            # Keep the strongest-weight angle per person
            if existing is None or angle.weight > existing["weight"]:
                per_url[url] = entry

    _save_cache(cache)

    ranked = sorted(per_url.values(), key=lambda x: (-x["weight"], x["name"]))
    return ranked[:max_matches]


# ── Blaze's real network (LinkedIn data export) ──────────────────────────────
# LinkedIn has no API for reading your connections, but it lets you download
# them: Settings → Data privacy → Get a copy of your data → Connections.
# Drop the Connections.csv here (gitignored — it's PII).

CONNECTIONS_CSV = os.getenv(
    "LINKEDIN_CONNECTIONS_CSV",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "linkedin_connections.csv"),
)

_COMPANY_SUFFIXES = {"inc", "llc", "ltd", "corp", "corporation", "co", "company", "the", "pbc"}
_connections_cache: Optional[list[dict]] = None


def _norm_company(name: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower()).split()
    return " ".join(w for w in words if w not in _COMPANY_SUFFIXES)


def load_connections(path: str = CONNECTIONS_CSV) -> list[dict]:
    """Read LinkedIn's Connections.csv. It starts with a few 'Notes:' lines
    before the real header row, so skip to the line that begins 'First Name'."""
    global _connections_cache
    if _connections_cache is not None:
        return _connections_cache
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            lines = f.readlines()
        start = next((i for i, l in enumerate(lines) if l.startswith("First Name")), None)
        if start is None:
            log.warning(f"{path}: no 'First Name' header row found")
        else:
            for r in csv.DictReader(lines[start:]):
                name = f"{r.get('First Name', '')} {r.get('Last Name', '')}".strip()
                if not name:
                    continue
                rows.append({
                    "name": name,
                    "company": (r.get("Company") or "").strip(),
                    "position": (r.get("Position") or "").strip(),
                    "linkedin": (r.get("URL") or "").strip(),
                })
            log.info(f"loaded {len(rows)} LinkedIn connections")
    except FileNotFoundError:
        log.info(f"no LinkedIn connections export at {path} — skipping 1st-degree check")
    _connections_cache = rows
    return rows


def find_connections_at(company: str) -> list[dict]:
    """1st-degree connections whose current company matches. Matches exact
    names after dropping Inc/LLC/etc, plus 'Figure' ↔ 'Figure AI' style prefixes."""
    target = _norm_company(company)
    if len(target) < 3:
        return []
    hits = []
    for c in load_connections():
        theirs = _norm_company(c["company"])
        if not theirs:
            continue
        if theirs == target or theirs.startswith(target + " ") or target.startswith(theirs + " "):
            hits.append(c)
    return hits


def network_search_url(company: str, degree: str = "S") -> str:
    """LinkedIn people search for the company, limited to your network.
    degree "S" = 2nd-degree (LinkedIn shows the mutual connection on each
    result), "F" = 1st-degree. Opened by Blaze himself — no scraping."""
    return (
        "https://www.linkedin.com/search/results/people/"
        f"?keywords={quote_plus(company)}&network=%5B%22{degree}%22%5D"
    )


def enrich_job(job: dict, min_score_for_lookup: int = 8) -> dict:
    """
    Called from ares.py after AI scoring. Always attaches Blaze's real
    1st-degree `connections` at the company and a `network_url` for his
    2nd-degree network. Attaches `warm_matches` (strangers with a shared
    background) only when the score meets threshold, to conserve search budget.
    """
    company = (job.get("company") or "").strip()
    if not company:
        return job

    job["connections"] = find_connections_at(company)
    job["network_url"] = network_search_url(company)
    if job["connections"]:
        log.info(f"[{company}] {len(job['connections'])} 1st-degree connection(s)")

    try:
        score = int(job.get("score", 0))
    except (TypeError, ValueError):
        score = 0

    if score < min_score_for_lookup:
        return job

    try:
        matches = find_matches_for_company(company)
        if matches:
            job["warm_matches"] = matches
            log.info(f"[{company}] attached {len(matches)} warm match(es)")
    except Exception as e:
        log.error(f"warm-match lookup failed for {company!r}: {e}")

    return job


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
    import sys
    company = " ".join(sys.argv[1:]) or "Waymo"
    print(f"1st-degree connections at {company}:")
    for c in find_connections_at(company):
        print(f"  {c['name']} — {c['position']} @ {c['company']}")
    print(f"2nd-degree search: {network_search_url(company)}")
    print(f"looking up warm matches at: {company}")
    for m in find_matches_for_company(company):
        print(f"  [{m['weight']}] {m['name']} — {m['angle']}")
        print(f"      {m['linkedin']}")
        if m["snippet"]:
            print(f"      snippet: {m['snippet']}")
