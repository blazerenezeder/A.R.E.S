#!/usr/bin/env python3
"""
A.R.E.S. — Autonomous Role Extraction System
A personal job acquisition agent.
Runs daily at 7am. Finds roles. Scores them. Enriches with hiring manager
and company address. Drafts professional cover letters. Texts for approval.

Setup:
1. Copy .env.example to .env and fill in your credentials
2. Run: python ares.py
3. Or test with: python ares.py test
"""

import os
import re
import json
import time
import logging
import hashlib
import subprocess
import requests
import schedule
from datetime import datetime
from bs4 import BeautifulSoup
from anthropic import Anthropic
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger("ARES")
if not log.handlers:
    log.setLevel(logging.INFO)
    fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    fh = logging.FileHandler(os.path.join(os.path.dirname(__file__), "ares.log"))
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(fh)
    log.addHandler(sh)
    log.propagate = False

# ── Credentials (loaded from .env) ────────────────────────────────────────────

PHONE_NUMBER    = os.getenv("MY_PHONE")
TWILIO_FROM     = os.getenv("TWILIO_FROM")
TWILIO_SID      = os.getenv("TWILIO_SID")
TWILIO_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN")
CLAUDE_API_KEY  = os.getenv("ANTHROPIC_API_KEY")
HUNTER_API_KEY  = os.getenv("HUNTER_API_KEY")

SEEN_JOBS_FILE  = "ares_seen.json"
PENDING_FILE    = "ares_pending.json"
INBOX_DIR       = os.path.join(os.path.dirname(__file__), "inbox")

# ── Candidate profile ─────────────────────────────────────────────────────────

CANDIDATE_NAME = os.getenv("CANDIDATE_NAME", "Blaze Renezeder")

CANDIDATE_PROFILE = """
Blaze Renezeder. 24. San Francisco. Operations professional with a builder mindset.
Experience: Universal Banker at Partners Bank of California (million-dollar transactions, legal settlement disbursements, zero compliance errors across 11 months), GTM and Operations at Beer Girl (founder-led startup, 15 clients, loaded metric tons of kegs with a forklift never used before, drove hundreds of miles, ran marketing events until midnight), M&A Sourcing Analyst at Rejigg (full autonomous deal pipeline ownership), Event Coordinator at Wagon Wheel Brewing (100+ events, vendor contracts, on-time on-budget), Operations Lead at Coast Film Festival (2500-person concert, zero queue delays, volunteer team management). Built A.R.E.S. - Autonomous Role Extraction System - from scratch in two days with zero coding background. Currently building OpenClaw, a personal AI operating system. Eagle Scout. 1st Degree Black Belt Taekwondo. Student Pilot 9hrs Piper Cherokee. Varsity volleyball sophomore year. Target roles: Operations Coordinator, Program Manager, Chief of Staff, BizOps, Deployment Operations, Strategic Events, Launch Operations, Field Operations, Executive Operations. Roles close to founders with real ownership and no defined playbook. No engineering degree. No clearance. No sponsorship needed. Location San Francisco Bay Area only. Will commute to Peninsula or South Bay. Dream companies: Physical Intelligence, Generalist AI, Figure AI, Vast Space, Built Robotics, Boom Supersonic, Wisk Aero, Archer Aviation, Planet Labs, Waymo, Zoox, Nuro, Relativity Space, Muon Space, Varda Space, Redwood Materials, Apptronik. The higher the mission on the scale of moving humanity forward - getting to Mars, making robots work with human-level dexterity, building the infrastructure of the future, clean energy, autonomous transportation at scale - the more bullish he is, provided the mission does not come at the cost of morality or human wellbeing. No defense. No weapons. No surveillance. No harm. He wants to work at companies building things that physically exist in the world. Small teams. Real consequences. Founder proximity. Mission worth telling people about. He figures out what needs to be done and does it without being asked.
"""

# ── Candidate contact info (fill in your own) ─────────────────────────────────

CANDIDATE = {
    "name":        os.getenv("CANDIDATE_NAME", ""),
    "email":       os.getenv("CANDIDATE_EMAIL", ""),
    "phone":       os.getenv("CANDIDATE_PHONE", ""),
    "address":     os.getenv("CANDIDATE_ADDRESS", ""),
    "city":        os.getenv("CANDIDATE_CITY", ""),
    "state":       os.getenv("CANDIDATE_STATE", "CA"),
    "zip":         os.getenv("CANDIDATE_ZIP", ""),
    "linkedin":    os.getenv("CANDIDATE_LINKEDIN", ""),
    "authorized":  "Yes",
    "sponsorship": "No",
    "salary_min":  int(os.getenv("CANDIDATE_SALARY_MIN", "0")),
    "salary_floor": int(os.getenv("CANDIDATE_SALARY_FLOOR", "0")),
    "resume_path": os.getenv("CANDIDATE_RESUME", "/Users/icebear/Desktop/Blaze_Renezeder_Resume.pdf"),
}

# ── Canned answers in Blaze's voice ──────────────────────────────────────────

CANNED_ANSWERS = {
    "strength": (
        "My greatest strength is operational excellence. I have a genuine ability to wear "
        "multiple hats and I get energized by it, not worn down. Whether I am managing "
        "a vendor relationship, coordinating logistics, or running a marketing event, I "
        "treat every responsibility as something I own end to end. I do not wait to be "
        "told what needs to happen next."
    ),
    "no_playbook": (
        "At Beer Girl I had to orchestrate a one-ton shipment of beer across over 300 miles "
        "with no manual, no precedent, and a marketing event the same night. I coordinated "
        "directly with suppliers to determine exactly which SKUs needed to be at each stop, "
        "loaded everything into a Sprinter van safely and alone, and then offloaded by hand "
        "across accounts in San Diego, Orange County, Los Angeles, the Inland Empire, Oxnard, "
        "and Santa Barbara before arriving to set up and run the event. Everything got there "
        "on time and nothing went wrong. I figured it out as it needed to be figured out."
    ),
    "why_here": (
        "I want to be close to a mission that physically changes something in the world. "
        "This company is building that. I am drawn to teams where the work has real "
        "consequences and where the people around you are genuinely trying to solve "
        "something hard. That is the environment I do my best work in."
    ),
    "salary": "My target is $110,000, though I am open to discussing total compensation based on the role and opportunity.",
    "salary_generational": "I am flexible on compensation for the right opportunity. I am more focused on mission fit and real ownership than hitting a specific number.",
    "start_date": "I am available to start immediately.",
    "relocate": "I am based in San Francisco and am not looking to relocate.",
    "experience_years": "I have three years of operations and coordination experience across startups, financial services, and events.",
    "cover_letter_summary": (
        "Operations professional with a builder's mindset. Proven across high-stakes logistics, "
        "financial operations, and event execution. I figure out what needs to happen and I make "
        "it happen without being asked."
    ),
}

# ── Target companies ──────────────────────────────────────────────────────────

CAREER_PAGES = [
    {"name": "Zipline",          "url": "https://flyzipline.com/careers",               "domain": "flyzipline.com"},
    {"name": "Planet Labs",      "url": "https://www.planet.com/company/careers/",       "domain": "planet.com"},
    {"name": "Waymo",            "url": "https://waymo.com/careers/",                    "domain": "waymo.com"},
    {"name": "Zoox",             "url": "https://zoox.com/careers/",                     "domain": "zoox.com"},
    {"name": "Archer Aviation",  "url": "https://www.archer.com/careers",                "domain": "archer.com"},
    {"name": "Saildrone",        "url": "https://www.saildrone.com/careers",             "domain": "saildrone.com"},
    {"name": "Astro Mechanica",  "url": "https://www.astromechanica.com/careers",        "domain": "astromechanica.com"},
    {"name": "Wisk Aero",        "url": "https://wisk.aero/careers/",                   "domain": "wisk.aero"},
    {"name": "Pixar",            "url": "https://www.pixar.com/careers",                 "domain": "pixar.com"},
    {"name": "ILM",              "url": "https://www.ilm.com/careers/",                  "domain": "ilm.com"},
    {"name": "Lucasfilm",        "url": "https://www.lucasfilm.com/careers/",            "domain": "lucasfilm.com"},
    {"name": "Relativity Space", "url": "https://www.relativityspace.com/careers",       "domain": "relativityspace.com"},
    {"name": "Muon Space",       "url": "https://www.muonspace.com/careers",             "domain": "muonspace.com"},
    {"name": "Starcloud",        "url": "https://job-boards.greenhouse.io/starcloud",     "domain": "starcloud.com"},
]

ASHBY_SEARCHES = [
    'https://jobs.ashbyhq.com/search?query=operations&location=San+Francisco',
    'https://jobs.ashbyhq.com/search?query=program+manager&location=San+Francisco',
    'https://jobs.ashbyhq.com/search?query=chief+of+staff&location=San+Francisco',
    'https://jobs.ashbyhq.com/search?query=biz+ops&location=San+Francisco',
    'https://jobs.ashbyhq.com/search?query=launch+operations&location=San+Francisco',
    'https://jobs.ashbyhq.com/search?query=field+operations&location=San+Francisco',
    'https://jobs.ashbyhq.com/search?query=coordinator&location=San+Francisco',
    'https://jobs.ashbyhq.com/search?query=deployment&location=San+Francisco',
]

INDEED_SEARCHES = [
    "operations coordinator aerospace San Francisco",
    "chief of staff startup San Francisco",
    "biz ops associate San Francisco startup",
    "program manager robotics Bay Area",
    "launch operations coordinator Bay Area",
    "deployment operations San Francisco",
    "strategic events coordinator San Francisco",
    "field operations associate Bay Area",
    "operations associate AI company San Francisco",
    "coordinator autonomous vehicles Bay Area",
    "chief of staff AI robotics San Francisco",
    "operations generalist startup Bay Area",
    "field operations associate Bay Area",
    "launch operations coordinator San Francisco",
    "production coordinator film Bay Area",
    "site operations aviation San Francisco",
    "ground operations space Bay Area",
    "operations associate startup San Francisco",
    "flight operations coordinator California",
    "facilities coordinator San Francisco",
    "studio operations coordinator Bay Area",
    "mission operations associate Bay Area",
    "program coordinator aerospace San Francisco",
]

ROLE_KEYWORDS = [
    "operations", "coordinator", "logistics", "field", "launch",
    "production", "ground", "site", "facilities", "program",
    "mission", "flight", "test", "studio", "associate", "specialist",
]

EXCLUDE_KEYWORDS = [
    "saildrone", "defense", "weapons", "classified", "secret clearance", "top secret",
    "senior director", "vp ", "vice president", "principal",
    "software engineer", "machine learning", "data scientist",
    "frontend", "backend", "fullstack", "devops", "sre",
    "10+ years", "8+ years", "7+ years", "7 years", "8 years", "10 years",
    "mechanical engineer", "electrical engineer", "systems engineer",
    "oem", "manufacturing engineer", "process engineer",
    "supply chain manager", "supply chain director",
    "senior manager", "senior engineer", "staff engineer",
    "phd", "masters degree", "master's degree", "p.e. license",
    "bachelor's degree in engineering", "bachelor of engineering",
    "b.s. in engineering", "bs in engineering", "b.s. engineering",
    "degree in aerospace", "degree in mechanical", "degree in electrical",
    "degree in computer science", "degree in physics",
    "engineering degree required", "requires an engineering degree",
]

TOO_FAR_LOCATIONS = [
    "los angeles", " la,", "san diego", "seattle", "new york",
    "austin", "denver", "chicago", "boston", "atlanta", "portland",
    "antioch",
]

TARGET_COMPANIES = [
    "zipline", "planet labs", "waymo", "zoox", "archer",
    "saildrone", "astro mechanica", "wisk", "pixar", "ilm",
    "lucasfilm", "relativity space", "muon space",
    # Space
    "spire", "loft orbital", "momentus", "swift navigation", "longshot",
    "array labs", "astra", "samara", "aetherflux", "orbital composites",
    "lyra space", "elodin", "cosmic robotics", "armada", "azora",
    # Dexterous robotics (Bay Area)
    "covariant", "dexterity", "physical intelligence", "apptronik", "figure", "1x technologies",
    # Hypersonic (Bay Area)
    "exosonic", "boom supersonic", "vast",
    # Orbital compute
    "starcloud", "lumen orbit",
]

# ── Utilities ─────────────────────────────────────────────────────────────────

BAY_AREA_SIGNALS = [
    "san francisco", " sf,", "sf ", "bay area", "mountain view", "palo alto",
    "sunnyvale", "santa clara", "san jose", "oakland", "berkeley",
    "south san francisco", "redwood city", "menlo park", "fremont",
    "remote", "hybrid", "n/a", "multiple", "perm", "usa", "united states",
    "ca,", ", ca", "california",
]

def is_bay_area(location: str, strict: bool = False) -> bool:
    if not location:
        return True
    loc = location.lower()
    if strict:
        return any(s in loc for s in BAY_AREA_SIGNALS)
    return not any(f in loc for f in TOO_FAR_LOCATIONS)

def is_target_company(company: str) -> bool:
    return any(t in company.lower() for t in TARGET_COMPANIES)

def load_seen() -> set:
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE) as f:
            return set(json.load(f))
    return set()

def save_seen(seen: set):
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(list(seen), f)

def load_pending() -> list:
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE) as f:
            return json.load(f)
    return []

def save_pending(pending: list):
    with open(PENDING_FILE, "w") as f:
        json.dump(pending, f, indent=2)

def parse_salary(text: str) -> tuple:
    import re
    text = text.lower().replace(",", "").replace("k", "000")
    matches = re.findall(r'\$?\s*(\d{4,6})', text)
    nums = [int(m) for m in matches if 30000 <= int(m) <= 500000]
    if len(nums) >= 2:
        return min(nums), max(nums)
    elif len(nums) == 1:
        return nums[0], nums[0]
    return None, None

def salary_ok(job: dict) -> bool:
    sal_min, sal_max = parse_salary(job.get("description", "") + " " + job.get("title", ""))
    if sal_min is None:
        return True
    if sal_max < CANDIDATE["salary_floor"]:
        return False
    if sal_min < CANDIDATE["salary_min"] and not is_target_company(job.get("company", "")):
        return False
    return True

def format_salary(job: dict) -> str:
    sal_min, sal_max = parse_salary(job.get("description", "") + " " + job.get("title", ""))
    if sal_min is None:
        return "Salary not listed"
    if sal_min == sal_max:
        return f"${sal_min:,}"
    return f"${sal_min:,} - ${sal_max:,}"

# ── Hunter.io — hiring manager lookup ────────────────────────────────────────

def get_hiring_manager(domain: str, company_name: str) -> str:
    if not HUNTER_API_KEY or not domain:
        return ""
    try:
        url = f"https://api.hunter.io/v2/domain-search?domain={domain}&api_key={HUNTER_API_KEY}&limit=10"
        r = requests.get(url, timeout=10)
        data = r.json()
        emails = data.get("data", {}).get("emails", [])
        priority_titles = ["recruiter", "talent", "hiring", "people", "hr", "operations", "head of"]
        for email in emails:
            title = (email.get("position") or "").lower()
            if any(p in title for p in priority_titles):
                first = email.get("first_name", "")
                last = email.get("last_name", "")
                if first:
                    return f"{first} {last}".strip()
        if emails:
            first = emails[0].get("first_name", "")
            last = emails[0].get("last_name", "")
            if first:
                return f"{first} {last}".strip()
    except Exception as e:
        log.warning(f"Hunter.io lookup failed for {domain}: {e}")
    return ""

# ── CA Secretary of State — company address ───────────────────────────────────

def get_company_address(company_name: str) -> str:
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        api_url = f"https://bizfileonline.sos.ca.gov/api/Records/businesses/search?SearchTerm={requests.utils.quote(company_name)}&SearchType=OWNER_NAME&Status=ACTIVE&Source=CORP"
        r = requests.get(api_url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            results = data.get("hits", {}).get("hits", [])
            if results:
                source = results[0].get("_source", {})
                addr = source.get("addressLine1", "")
                city = source.get("city", "")
                state = source.get("state", "CA")
                zipcode = source.get("postalCode", "")
                if addr and city:
                    return f"{addr}\n{city}, {state} {zipcode}"
    except Exception as e:
        log.warning(f"CA SOS lookup failed for {company_name}: {e}")
    return ""

# ── Job fetching ──────────────────────────────────────────────────────────────

def fetch_indeed_jobs() -> list:
    jobs = []
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    for query in INDEED_SEARCHES:
        try:
            url = f"https://www.indeed.com/jobs?q={requests.utils.quote(query)}&l=San+Francisco+Bay+Area%2C+CA&radius=15&sort=date&fromage=5"
            r = requests.get(url, headers=headers, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.find_all("div", class_=lambda c: c and "job_seen_beacon" in c)
            if not cards:
                cards = soup.find_all("td", class_=lambda c: c and "resultContent" in c)
            for card in cards[:8]:
                title_el = card.find(["h2", "span"], class_=lambda c: c and "jobTitle" in (c or ""))
                company_el = card.find(attrs={"data-testid": "company-name"})
                location_el = card.find(attrs={"data-testid": "text-location"})
                link_el = card.find("a", href=True)
                title = title_el.get_text(strip=True) if title_el else ""
                if not title:
                    continue
                company = company_el.get_text(strip=True) if company_el else "Unknown"
                location = location_el.get_text(strip=True) if location_el else "Bay Area"
                href = link_el["href"] if link_el else ""
                link = f"https://www.indeed.com{href}" if href.startswith("/") else href
                jobs.append({
                    "id": hashlib.md5(f"{title}{company}".encode()).hexdigest(),
                    "title": title, "company": company, "location": location,
                    "link": link, "description": f"{title} at {company} in {location}",
                    "source": "indeed", "domain": "", "date_flag": "within 5 days"
                })
            time.sleep(1)
        except Exception as e:
            log.warning(f"Indeed failed for '{query}': {e}")
    log.info(f"Indeed: {len(jobs)} raw jobs")
    return jobs

GREENHOUSE_COMPANIES = [
    {"name": "Waymo",              "slug": "waymo"},
    {"name": "Planet Labs",        "slug": "planetlabs"},
    {"name": "Zoox",               "slug": "zoox"},
    {"name": "Relativity Space",   "slug": "relativity"},
    {"name": "Wisk Aero",          "slug": "wiskaero"},
    {"name": "Zipline",            "slug": "ziplineinternational"},
    {"name": "Archer Aviation",    "slug": "archer"},
    {"name": "Muon Space",         "slug": "muonspace"},
    {"name": "Starcloud",          "slug": "starcloud"},
    {"name": "Saildrone",          "slug": "saildrone"},
    {"name": "Figure AI",          "slug": "figure"},
    {"name": "Built Robotics",     "slug": "builtrobotics"},
    {"name": "Nuro",               "slug": "nuro"},
    {"name": "Redwood Materials",  "slug": "redwoodmaterials"},
    # Bay Area Space Ecosystem additions
    {"name": "Spire Global",       "slug": "spire"},
    {"name": "Loft Orbital",       "slug": "loftorbital"},
    {"name": "Momentus",           "slug": "momentus"},
    {"name": "Swift Navigation",   "slug": "swiftnavigation"},
    {"name": "Longshot Space",     "slug": "longshotspace"},
    {"name": "Array Labs",         "slug": "arraylabs"},
    {"name": "Astra",              "slug": "astra"},
    {"name": "Astro Mechanica",    "slug": "astromechanica"},
    {"name": "Samara Aerospace",   "slug": "samara"},
    {"name": "AetherFlux",         "slug": "aetherflux"},
    {"name": "Orbital Composites", "slug": "orbitalcomposites"},
    {"name": "Lyra Space",         "slug": "lyraspace"},
    {"name": "Elodin Systems",     "slug": "elodin"},
    {"name": "Cosmic Robotics",    "slug": "cosmicrobotics"},
    # Dexterous robotics (Bay Area only)
    {"name": "Covariant",          "slug": "covariant"},
    {"name": "Dexterity",          "slug": "dexterity"},
    # Hypersonic (Bay Area only)
    {"name": "Exosonic",           "slug": "exosonic"},
]

LEVER_COMPANIES = [
    {"name": "Archer Aviation",       "slug": "archer-aviation"},
    {"name": "Relativity Space",      "slug": "relativityspace"},
    {"name": "Wisk Aero",             "slug": "wisk"},
    {"name": "Boom Supersonic",       "slug": "boomsupersonic"},
    {"name": "Physical Intelligence", "slug": "physical-intelligence"},
    {"name": "Apptronik",             "slug": "apptronik"},
    {"name": "Vast Space",            "slug": "vast"},
    # Bay Area Space Ecosystem additions
    {"name": "Spire Global",          "slug": "spire-global"},
    {"name": "Loft Orbital",          "slug": "loft-orbital"},
    {"name": "Swift Navigation",      "slug": "swift-navigation"},
    {"name": "Momentus",              "slug": "momentus-space"},
    {"name": "Armada",                "slug": "armada"},
    {"name": "Azora Space",           "slug": "azora"},
    # Dexterous robotics (Bay Area only)
    {"name": "1X Technologies",       "slug": "1x-technologies"},
]

def fetch_greenhouse_jobs() -> list:
    jobs = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for company in GREENHOUSE_COMPANIES:
        try:
            url = f"https://boards-api.greenhouse.io/v1/boards/{company['slug']}/jobs?content=true"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            data = r.json()
            for post in data.get("jobs", []):
                title = post.get("title", "")
                location = post.get("location", {}).get("name", "")
                link = post.get("absolute_url", "")
                content = post.get("content", "") or ""
                if not title:
                    continue
                jobs.append({
                    "id": hashlib.md5(f"{title}{company['name']}greenhouse".encode()).hexdigest(),
                    "title": title,
                    "company": company["name"],
                    "location": location,
                    "link": link,
                    "description": f"{title} at {company['name']} in {location}. {content[:400]}",
                    "source": "greenhouse",
                    "domain": "",
                    "date_flag": "Active Greenhouse listing"
                })
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Greenhouse failed for {company['name']}: {e}")
    log.info(f"Greenhouse: {len(jobs)} raw jobs")
    return jobs

def fetch_lever_jobs() -> list:
    jobs = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for company in LEVER_COMPANIES:
        try:
            url = f"https://api.lever.co/v0/postings/{company['slug']}?mode=json"
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code != 200:
                continue
            postings = r.json()
            for post in postings:
                title = post.get("text", "")
                location = post.get("categories", {}).get("location", "")
                link = post.get("hostedUrl", "")
                description = post.get("description", "") or ""
                if not title:
                    continue
                jobs.append({
                    "id": hashlib.md5(f"{title}{company['name']}lever".encode()).hexdigest(),
                    "title": title,
                    "company": company["name"],
                    "location": location,
                    "link": link,
                    "description": f"{title} at {company['name']} in {location}. {description[:400]}",
                    "source": "lever",
                    "domain": "",
                    "date_flag": "Active Lever listing"
                })
            time.sleep(0.5)
        except Exception as e:
            log.warning(f"Lever failed for {company['name']}: {e}")
    log.info(f"Lever: {len(jobs)} raw jobs")
    return jobs

def fetch_indeed_rss(query: str) -> list:
    jobs = []
    try:
        import xml.etree.ElementTree as ET
        url = f"https://www.indeed.com/rss?q={requests.utils.quote(query)}&l=San+Francisco+Bay+Area%2C+CA&radius=15&fromage=5"
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        root = ET.fromstring(r.content)
        for item in root.findall(".//item")[:8]:
            title = (item.findtext("title") or "").split(" - ")[0].strip()
            company = (item.findtext("title") or "").split(" - ")[1].strip() if " - " in (item.findtext("title") or "") else "Unknown"
            link = item.findtext("link") or ""
            description = item.findtext("description") or ""
            location_tag = item.find("{https://www.indeed.com/about/}loc")
            location = location_tag.text.strip() if location_tag is not None else "Bay Area"
            if not title:
                continue
            jobs.append({
                "id": hashlib.md5(f"{title}{company}".encode()).hexdigest(),
                "title": title, "company": company, "location": location,
                "link": link, "description": f"{title} at {company} in {location}. {description[:300]}",
                "source": "indeed_rss", "domain": "", "date_flag": "within 5 days"
            })
    except Exception as e:
        log.warning(f"Indeed RSS failed for '{query}': {e}")
    return jobs

def fetch_ashby_jobs() -> list:
    jobs = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    for search_url in ASHBY_SEARCHES:
        try:
            # Try Ashby's internal API first
            query_param = search_url.split("query=")[1].split("&")[0] if "query=" in search_url else ""
            api_url = "https://jobs.ashbyhq.com/api/non-user-graphql"
            payload = {
                "operationName": "ApiJobBoardWithSearch",
                "variables": {
                    "searchText": query_param.replace("+", " "),
                    "locationFilter": "San Francisco, CA"
                },
                "query": "query ApiJobBoardWithSearch($searchText: String, $locationFilter: String) { jobBoard { jobPostings(input: {searchText: $searchText, locationFilter: $locationFilter, status: Listed}) { id title locationName jobCategories { name } employmentType } } }"
            }
            r = requests.post(api_url, json=payload, headers=headers, timeout=15)
            if r.status_code == 200:
                data = r.json()
                postings = (data.get("data") or {}).get("jobBoard", {}).get("jobPostings", [])
                for post in postings[:10]:
                    title = post.get("title", "")
                    location = post.get("locationName", "Bay Area")
                    job_id = post.get("id", "")
                    link = f"https://jobs.ashbyhq.com/job/{job_id}" if job_id else search_url
                    if title:
                        jobs.append({
                            "id": hashlib.md5(f"{title}ashby{job_id}".encode()).hexdigest(),
                            "title": title, "company": "via Ashby", "location": location,
                            "link": link, "description": f"{title} in {location}",
                            "source": "ashby", "domain": "", "date_flag": "Active posting"
                        })
                if postings:
                    time.sleep(1)
                    continue
            # Fallback: scrape the search page HTML
            r = requests.get(search_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            # Ashby renders job cards with specific classes
            for card in soup.find_all(["a", "div"], class_=lambda c: c and ("job" in (c or "").lower() or "posting" in (c or "").lower())):
                title_el = card.find(["h3", "h2", "span", "p"])
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if len(title) < 5 or len(title) > 100:
                    continue
                href = card.get("href", "") if card.name == "a" else ""
                link = f"https://jobs.ashbyhq.com{href}" if href.startswith("/") else href or search_url
                jobs.append({
                    "id": hashlib.md5(f"{title}ashby".encode()).hexdigest(),
                    "title": title, "company": "via Ashby", "location": "Bay Area",
                    "link": link, "description": f"{title} (Ashby listing)",
                    "source": "ashby", "domain": "", "date_flag": "Active posting"
                })
            time.sleep(1)
        except Exception as e:
            log.warning(f"Ashby failed for '{search_url}': {e}")
    log.info(f"Ashby: {len(jobs)} raw jobs")
    return jobs

def fetch_career_page_jobs() -> list:
    jobs = []
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
    job_url_signals = [
        "job", "jobs", "position", "opening", "role", "career",
        "apply", "greenhouse", "lever", "workday", "ashby", "breezy"
    ]
    nav_ignore = [
        "about", "contact", "press", "blog", "team", "culture",
        "benefits", "twitter", "linkedin", "facebook", "instagram",
        "privacy", "terms", "cookie", "#", "mailto", "javascript"
    ]
    for company in CAREER_PAGES:
        try:
            r = requests.get(company["url"], headers=headers, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            found = []
            for link in soup.find_all("a", href=True):
                text = link.get_text(strip=True)
                href = link["href"].lower()
                if any(n in href for n in nav_ignore):
                    continue
                if any(n in text.lower() for n in ["home", "about", "contact", "blog"]):
                    continue
                if len(text) < 5 or len(text) > 120:
                    continue
                if not any(k in text.lower() for k in ROLE_KEYWORDS):
                    continue
                full_url = link["href"] if link["href"].startswith("http") else company["url"].rstrip("/") + "/" + link["href"].lstrip("/")
                found.append({
                    "id": hashlib.md5(f"{text}{company['name']}".encode()).hexdigest(),
                    "title": text,
                    "company": company["name"],
                    "location": "Bay Area — verify location",
                    "link": full_url,
                    "description": f"{text} at {company['name']}",
                    "source": "career_page",
                    "domain": company.get("domain", ""),
                    "date_flag": "Date unknown — verify posting is active"
                })
            seen_titles = set()
            for j in found:
                if j["title"] not in seen_titles:
                    seen_titles.add(j["title"])
                    jobs.append(j)
            time.sleep(1)
        except Exception as e:
            log.warning(f"Career page failed for {company['name']}: {e}")
    log.info(f"Career pages: {len(jobs)} raw jobs")
    return jobs

def fetch_all_jobs() -> list:
    all_jobs = fetch_greenhouse_jobs() + fetch_lever_jobs() + fetch_career_page_jobs() + fetch_ashby_jobs()
    # Try Indeed HTML scrape as supplemental (often breaks but worth trying)
    try:
        all_jobs += fetch_indeed_jobs()
    except Exception as e:
        log.warning(f"Indeed scrape skipped: {e}")
    seen_ids = set()
    unique = []
    for j in all_jobs:
        if j["id"] not in seen_ids:
            seen_ids.add(j["id"])
            unique.append(j)
    log.info(f"Total unique: {len(unique)}")
    return unique

# ── Filtering ─────────────────────────────────────────────────────────────────

PENDING_BROWSERS = {}

def ashby_apply(job):
    import asyncio
    import random
    from playwright.async_api import async_playwright

    async def human_type(element, text: str):
        await element.click()
        await asyncio.sleep(random.uniform(0.3, 0.7))
        for char in text:
            await element.type(char, delay=random.randint(40, 130))
            if random.random() < 0.04:  # occasional micro-pause like a human thinking
                await asyncio.sleep(random.uniform(0.2, 0.6))

    def pick_canned(question: str, company: str = "") -> str:
        q = question.lower()
        if any(x in q for x in ["strength", "excel", "best at"]):
            return CANNED_ANSWERS["strength"]
        if any(x in q for x in ["playbook", "ambiguous", "no direction", "figure out", "unstructured", "challenge"]):
            return CANNED_ANSWERS["no_playbook"]
        if any(x in q for x in ["why", "interest", "motivation", "drawn"]):
            return CANNED_ANSWERS["why_here"]
        if any(x in q for x in ["salary", "compensation", "pay", "rate"]):
            # Generational = space economy, supersonic travel, hardware robotics
            # These are worth taking below-market salary for
            generational = [
                # Space
                "vast", "varda", "relativity", "muon", "astro mechanica",
                "rocket lab", "astra", "firefly", "stoke", "umbra", "capella",
                "satellogic", "spire", "hawkeye", "loft orbital", "momentus",
                "longshot", "array labs", "samara", "aetherflux", "orbital composites",
                "lyra space", "elodin", "armada", "azora",
                # Hypersonic / frontier aviation (Bay Area)
                "boom", "exosonic",
                # Dexterous robotics (Bay Area)
                "physical intelligence", "figure", "apptronik", "built robotics",
                "1x technologies", "covariant", "dexterity",
            ]
            if any(g in company.lower() for g in generational):
                return CANNED_ANSWERS["salary_generational"]
            return CANNED_ANSWERS["salary"]
        if any(x in q for x in ["start", "available", "when"]):
            return CANNED_ANSWERS["start_date"]
        if any(x in q for x in ["relocat", "move", "remote"]):
            return CANNED_ANSWERS["relocate"]
        if any(x in q for x in ["year", "experience", "background"]):
            return CANNED_ANSWERS["experience_years"]
        return ""

    def ai_answer(question: str) -> str:
        prompt = f"""You are Blaze Renezeder filling out a job application. Answer this question in his voice.

Rules:
- Direct and confident, never sycophantic
- No bullet points, no dashes as punctuation
- No corporate buzzwords
- Under 120 words
- Sound like a sharp operator, not a resume

His background: Operations professional. Partners Bank — million-dollar transactions, zero errors. Beer Girl — loaded metric tons of kegs solo, ran 100-mile delivery routes, executed marketing events the same night. Rejigg — autonomous M&A deal pipeline. Eagle Scout. Student pilot. Taekwondo black belt. Built an AI job hunting agent from scratch with no coding background. Wants to work at companies building things that physically exist in the world. Direct, high-agency, no fluff.

Question: {question}"""
        client = Anthropic(api_key=CLAUDE_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=180,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()

    async def fill():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1440, "height": 900},
            )
            page = await context.new_page()
            await page.goto(job["link"], timeout=30000)
            await asyncio.sleep(random.uniform(1.5, 3.0))

            # Scroll down naturally before doing anything
            await page.evaluate("window.scrollBy(0, 200)")
            await asyncio.sleep(random.uniform(0.5, 1.2))

            # Click Apply button if present
            try:
                apply_btn = page.locator("button:has-text('Apply'), a:has-text('Apply')")
                if await apply_btn.count() > 0:
                    await apply_btn.first.scroll_into_view_if_needed()
                    await asyncio.sleep(random.uniform(0.4, 0.8))
                    await apply_btn.first.click()
                    await page.wait_for_selector("input[name=_systemfield_name]", timeout=10000)
                    await asyncio.sleep(random.uniform(0.8, 1.5))
            except: pass

            # Name
            try:
                name_inp = page.locator("input[name=_systemfield_name]")
                if await name_inp.count() > 0:
                    await name_inp.first.scroll_into_view_if_needed()
                    await human_type(name_inp.first, CANDIDATE["name"])
                    await asyncio.sleep(random.uniform(0.4, 0.9))
            except: pass

            # Email
            try:
                email_inp = page.locator("input[name=_systemfield_email]")
                if await email_inp.count() > 0:
                    await human_type(email_inp.first, CANDIDATE["email"])
                    await asyncio.sleep(random.uniform(0.3, 0.7))
            except: pass

            # Phone
            try:
                phone_inp = page.locator("input[name=_systemfield_phone], input[placeholder*=phone i]")
                if await phone_inp.count() > 0:
                    await human_type(phone_inp.first, CANDIDATE["phone"])
                    await asyncio.sleep(random.uniform(0.3, 0.6))
            except: pass

            # LinkedIn
            try:
                li = page.locator("input[placeholder*=linkedin i], input[name*=linkedin i]")
                if await li.count() > 0:
                    await human_type(li.first, CANDIDATE["linkedin"])
                    await asyncio.sleep(random.uniform(0.3, 0.6))
            except: pass

            # Resume upload
            try:
                resume_path = CANDIDATE.get("resume_path", "")
                if resume_path and os.path.exists(resume_path):
                    resume_inputs = page.locator("input[type=file]")
                    if await resume_inputs.count() > 0:
                        await resume_inputs.first.set_input_files(resume_path)
                        await asyncio.sleep(random.uniform(1.5, 2.5))
            except: pass

            # Checkboxes
            try:
                cb_locator = page.locator("input[type=checkbox]")
                count = await cb_locator.count()
                for i in range(count):
                    cb = cb_locator.nth(i)
                    try:
                        label_el = page.locator(f"label[for='{await cb.get_attribute('id')}']")
                        label = (await label_el.text_content() or "").lower() if await label_el.count() > 0 else ""
                        if not label:
                            label = (await cb.get_attribute("aria-label") or "").lower()
                        is_checked = await cb.is_checked()
                        if any(x in label for x in ["authorized", "legally", "work in"]):
                            if not is_checked:
                                await cb.click()
                                await asyncio.sleep(random.uniform(0.2, 0.5))
                        if any(x in label for x in ["sponsorship", "visa", "require"]):
                            if is_checked:
                                await cb.click()
                                await asyncio.sleep(random.uniform(0.2, 0.5))
                    except: pass
            except: pass

            # Text / textarea fields — smart matching then AI fallback
            try:
                inp_locator = page.locator("textarea, input[type=text]:not([name=_systemfield_name]):not([name=_systemfield_email])")
                count = await inp_locator.count()
                for i in range(count):
                    inp = inp_locator.nth(i)
                    try:
                        name_attr = await inp.get_attribute("name") or ""
                        placeholder = await inp.get_attribute("placeholder") or ""
                        aria = await inp.get_attribute("aria-label") or ""
                        existing = await inp.input_value()
                        if existing:
                            continue
                        question = placeholder or aria or name_attr
                        if not question or len(question) < 4:
                            continue
                        # Try canned answer first
                        answer = pick_canned(question, company=job.get("company", ""))
                        if not answer:
                            answer = ai_answer(question)
                        if answer:
                            await inp.scroll_into_view_if_needed()
                            await asyncio.sleep(random.uniform(0.5, 1.0))
                            await human_type(inp, answer)
                            await asyncio.sleep(random.uniform(0.4, 0.9))
                    except: pass
            except: pass

            job_id = job["id"][:6]
            PENDING_BROWSERS[job_id] = {"browser": browser, "page": page, "loop": asyncio.get_running_loop()}
            notify_apply(
                f"Form filled — {job['title']} @ {job['company']}\n"
                f"Check your Mac screen. Fields should be filled.\n\n"
                f"YES → submit\n"
                f"NO → cancel"
            )

            while job_id in PENDING_BROWSERS:
                await asyncio.sleep(2)

    asyncio.run(fill())

def is_ashby_job(job: dict) -> bool:
    url = job.get('url', '') or job.get('link', '')
    return 'ashbyhq.com' in url.lower() or 'ashby' in url.lower()

def is_greenhouse_job(job: dict) -> bool:
    url = job.get('link', '') or job.get('url', '')
    return 'greenhouse.io' in url.lower() or 'gh_jid=' in url.lower() or 'withwaymo.com/jobs' in url.lower()

def greenhouse_apply(job):
    import asyncio
    import random
    import tempfile
    from playwright.async_api import async_playwright

    async def human_type(element, text: str):
        await element.click()
        await asyncio.sleep(random.uniform(0.2, 0.5))
        for char in text:
            await element.type(char, delay=random.randint(40, 130))
            if random.random() < 0.04:
                await asyncio.sleep(random.uniform(0.2, 0.5))

    async def fill_by_label(form, label_substr, value, is_file=False, is_select=False):
        """Find an input/select in form whose label contains label_substr, then fill it."""
        try:
            inputs = form.locator("input, textarea, select")
            count = await inputs.count()
            for i in range(count):
                el = inputs.nth(i)
                el_id = await el.get_attribute("id") or ""
                if not el_id:
                    continue
                label = form.locator(f"label[for='{el_id}']")
                if await label.count() == 0:
                    continue
                label_text = (await label.text_content() or "").lower()
                if label_substr.lower() not in label_text:
                    continue
                await el.scroll_into_view_if_needed()
                await asyncio.sleep(random.uniform(0.2, 0.5))
                if is_file:
                    await el.set_input_files(value)
                    log.info(f"Uploaded file for label '{label_substr}'")
                elif is_select:
                    # Pick the best matching option
                    options = await el.locator("option").all()
                    for opt in options:
                        opt_text = (await opt.text_content() or "").lower()
                        if value.lower() in opt_text:
                            opt_val = await opt.get_attribute("value")
                            await el.select_option(value=opt_val)
                            log.info(f"Selected '{opt_text}' for label '{label_substr}'")
                            break
                else:
                    tag = await el.evaluate("el => el.tagName")
                    if tag == "TEXTAREA":
                        await el.fill(value)
                    else:
                        await el.clear()
                        await human_type(el, value)
                    log.info(f"Filled label '{label_substr}'")
                return True
        except Exception as e:
            log.warning(f"fill_by_label '{label_substr}': {e}")
        return False

    async def fill():
        cl_tmp = None
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1440, "height": 900},
            )
            page = await context.new_page()

            # Resolve Greenhouse embed URL
            raw_link = job["link"]
            if 'gh_jid=' in raw_link:
                gh_jid = raw_link.split('gh_jid=')[-1].split('&')[0]
                company_slug = job.get("company", "").lower().replace(" ", "")
                url = f"https://job-boards.greenhouse.io/{company_slug}/jobs/{gh_jid}"
            elif 'withwaymo.com/jobs' in raw_link:
                gh_jid = raw_link.split('gh_jid=')[-1].split('&')[0]
                url = f"https://job-boards.greenhouse.io/waymo/jobs/{gh_jid}"
            elif 'job-boards.greenhouse.io' in raw_link:
                url = raw_link
            else:
                url = raw_link

            log.info(f"Greenhouse apply: {url}")
            await page.goto(url, timeout=30000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await asyncio.sleep(random.uniform(2.0, 3.0))

            # Dismiss OneTrust on main page
            try:
                await page.evaluate("""
                    ['onetrust-consent-sdk','onetrust-banner-sdk','onetrust-pc-sdk',
                     'onetrust-pc-dark-filter','ot-sdk-container'].forEach(id => {
                        const el = document.getElementById(id); if (el) el.remove();
                    });
                    document.querySelectorAll('.onetrust-pc-dark-filter,.ot-fade-in')
                        .forEach(el => el.remove());
                    document.body.style.overflow = '';
                """)
                log.info("OneTrust overlay cleared")
            except Exception as e:
                log.warning(f"Cookie banner clear: {e}")

            # The real application form lives inside a Greenhouse embed iframe.
            # Find it by URL pattern; fall back to main page if not found.
            gh_frame = None
            for frame in page.frames:
                if 'greenhouse.io/embed/job_app' in frame.url or 'greenhouse.io' in frame.url:
                    gh_frame = frame
                    log.info(f"Found Greenhouse iframe: {frame.url[:80]}")
                    break

            # Use the iframe's locator context; fall back to page if no iframe found
            ctx = gh_frame if gh_frame else page
            app_form = ctx.locator("#application-form") if gh_frame else page.locator("form").first
            log.info(f"Using {'iframe' if gh_frame else 'main page'} context")

            first_name, *last_parts = CANDIDATE["name"].split()
            last_name = " ".join(last_parts)

            async def fill_field(selector, value, is_file=False):
                try:
                    el = ctx.locator(selector).first
                    if await el.count() == 0:
                        log.warning(f"Field not found: {selector}")
                        return False
                    await el.scroll_into_view_if_needed()
                    await asyncio.sleep(random.uniform(0.2, 0.4))
                    if is_file:
                        await el.set_input_files(value)
                    else:
                        await el.fill("")
                        await human_type(el, value)
                    log.info(f"Filled {selector}")
                    return True
                except Exception as e:
                    log.warning(f"fill_field '{selector}': {e}")
                    return False

            async def fill_select(selector, value):
                try:
                    el = ctx.locator(selector).first
                    if await el.count() == 0:
                        return False
                    options = await el.locator("option").all()
                    for opt in options:
                        text = (await opt.text_content() or "").lower()
                        if value.lower() in text:
                            opt_val = await opt.get_attribute("value")
                            await el.select_option(value=opt_val)
                            log.info(f"Selected '{text}' for {selector}")
                            return True
                except Exception as e:
                    log.warning(f"fill_select '{selector}': {e}")
                return False

            # Core fields — all standard Greenhouse IDs
            await fill_field("#first_name", first_name)
            await asyncio.sleep(random.uniform(0.3, 0.5))
            await fill_field("#last_name", last_name)
            await asyncio.sleep(random.uniform(0.3, 0.5))
            await fill_field("#email", CANDIDATE["email"])
            await asyncio.sleep(random.uniform(0.3, 0.5))
            await fill_field("#phone", CANDIDATE["phone"])
            await asyncio.sleep(random.uniform(0.3, 0.5))

            # Country — type "United States" and pick from autocomplete dropdown
            try:
                country_el = ctx.locator("#country").first
                if await country_el.count() > 0:
                    await country_el.scroll_into_view_if_needed()
                    await country_el.fill("")
                    await human_type(country_el, "United States")
                    await asyncio.sleep(0.8)
                    option = ctx.locator("li:has-text('United States'), [role='option']:has-text('United States')").first
                    if await option.count() > 0:
                        await option.click()
                        log.info("Selected country: United States")
                    await asyncio.sleep(0.4)
            except Exception as e:
                log.warning(f"Country field: {e}")

            # Location (city) — standard Greenhouse field on some boards
            try:
                loc_el = ctx.locator("#candidate-location").first
                if await loc_el.count() > 0:
                    await loc_el.scroll_into_view_if_needed()
                    await fill_field("#candidate-location", CANDIDATE.get("city", "San Francisco"))
                    log.info("Filled location")
                    await asyncio.sleep(0.3)
            except Exception as e:
                log.warning(f"Location field: {e}")

            # Resume upload
            resume_path = CANDIDATE.get("resume_path", "")
            if resume_path and os.path.exists(resume_path):
                await fill_field("#resume", resume_path, is_file=True)
                await asyncio.sleep(random.uniform(1.0, 2.0))

            # Cover letter — generate PDF, send to Telegram for review, then upload
            cl_text = job.get("cover_letter", "")
            if cl_text:
                try:
                    notify_apply(
                        f"Cover Letter — {job['title']} @ {job['company']}\n\n{cl_text[:3500]}"
                    )
                    cl_path = os.path.join(tempfile.gettempdir(), "Blaze_Renezeder_Cover_Letter.pdf")
                    try:
                        from fpdf import FPDF
                        # Clean up the text: collapse single newlines within paragraphs
                        # so multi_cell wraps naturally without mid-sentence breaks
                        import re as _re
                        paragraphs = _re.split(r'\n{2,}', cl_text.strip())
                        clean_lines = []
                        for para in paragraphs:
                            clean_lines.append(" ".join(para.split("\n")))
                            clean_lines.append("")  # blank line between paragraphs

                        pdf = FPDF()
                        pdf.set_margins(20, 20, 20)
                        pdf.set_auto_page_break(auto=True, margin=15)
                        pdf.add_page()
                        pdf.set_font("Helvetica", size=11)
                        w = pdf.w - pdf.l_margin - pdf.r_margin
                        for line in clean_lines:
                            pdf.multi_cell(w, 6, line if line.strip() else " ")
                        pdf.output(cl_path)
                        log.info(f"Cover letter PDF written: {cl_path}")
                    except Exception as pdf_err:
                        log.warning(f"PDF generation failed ({pdf_err}), falling back to .txt")
                        cl_path = cl_path.replace(".pdf", ".txt")
                        with open(cl_path, "w") as f:
                            f.write(cl_text)
                    uploaded = await fill_field("#cover_letter", cl_path, is_file=True)
                    if uploaded:
                        await asyncio.sleep(random.uniform(1.0, 2.0))
                    else:
                        log.warning("Cover letter upload failed")
                except Exception as e:
                    log.warning(f"Cover letter: {e}")

            # LinkedIn — try Nuro-specific ID first, then a16z ID, then label-based
            linkedin_filled = await fill_field("#question_64846643", CANDIDATE["linkedin"])
            if not linkedin_filled:
                linkedin_filled = await fill_field("#question_30593568003", CANDIDATE["linkedin"])
            if not linkedin_filled:
                await fill_by_label(app_form, "linkedin", CANDIDATE["linkedin"])
            await asyncio.sleep(random.uniform(0.3, 0.5))

            # Greenhouse custom dropdowns — click input, wait, pick option
            async def fill_gh_dropdown(field_id, answer):
                try:
                    # Use attribute selector to handle IDs with special chars like []
                    inp = ctx.locator(f"[id='{field_id}']").first
                    if await inp.count() == 0:
                        log.warning(f"Dropdown not found: id={field_id}")
                        return
                    await inp.scroll_into_view_if_needed()
                    await inp.click()
                    await asyncio.sleep(0.6)
                    # Escape single quotes in answer text so CSS :has-text() doesn't break
                    # on phrases like "I don't have a disability"
                    escaped = answer.replace("\\", "\\\\").replace("'", "\\'")
                    opt = ctx.locator(f"li:has-text('{escaped}'), [role='option']:has-text('{escaped}')").first
                    if await opt.count() > 0:
                        await opt.click()
                        log.info(f"GH dropdown {field_id} → '{answer}'")
                    else:
                        await inp.fill(answer)
                        log.info(f"GH field {field_id} typed → '{answer}'")
                    await asyncio.sleep(0.4)
                except Exception as e:
                    log.warning(f"fill_gh_dropdown {field_id}: {e}")

            # a16z specific: related to a16z employee → No
            await fill_gh_dropdown("question_30593569003", "No")

            # Nuro specific — compensation + on-site
            await fill_gh_dropdown("question_64846644", "Yes")
            await fill_gh_dropdown("question_64846645", "Yes")

            # Shift availability checkboxes — Morning Sun-Thu + Afternoon Sun-Thu
            # IDs contain [] so must use attribute selector not CSS ID shorthand
            for cb_id in ["question_64846646[]_657135964", "question_64846646[]_684766153"]:
                try:
                    cb = ctx.locator(f"[id='{cb_id}']").first
                    if await cb.count() > 0 and not await cb.is_checked():
                        await cb.check()
                        log.info(f"Checked shift: {cb_id}")
                    await asyncio.sleep(0.2)
                except Exception as e:
                    log.warning(f"Shift checkbox {cb_id}: {e}")

            # Previous Nuro employee: No
            await fill_gh_dropdown("question_64846647", "No")
            # Work authorization: Yes
            await fill_gh_dropdown("question_64846648", "Yes")
            # Sponsorship needed: No
            await fill_gh_dropdown("question_64846649", "No")

            # Website (leave blank if no portfolio)
            website = CANDIDATE.get("website", "")
            if website:
                await fill_by_label(app_form, "website", website)

            # Standard label-based selects (non-Nuro Greenhouse forms)
            await fill_by_label(app_form, "work authorization", "authorized", is_select=True)
            await asyncio.sleep(random.uniform(0.3, 0.5))
            await fill_by_label(app_form, "state", "california", is_select=True)
            await asyncio.sleep(random.uniform(0.3, 0.5))
            await fill_by_label(app_form, "full legal name", CANDIDATE["name"])
            await asyncio.sleep(random.uniform(0.3, 0.5))
            await fill_by_label(app_form, "alphabet employee", "no", is_select=True)
            await asyncio.sleep(random.uniform(0.3, 0.5))

            # EEO — Blaze's actual answers (Greenhouse custom dropdowns)
            await fill_gh_dropdown("gender", "Male")
            await fill_gh_dropdown("hispanic_ethnicity", "No")
            await asyncio.sleep(0.8)
            # After selecting "No" for hispanic, a race dropdown appears
            await fill_gh_dropdown("race", "White")
            await fill_gh_dropdown("veteran_status", "I am not a protected veteran")
            await fill_gh_dropdown("disability_status", "No, I don't have a disability")

            # Declaration checkbox
            try:
                decl = ctx.locator("input[type='checkbox'][id*='declaration']")
                if await decl.count() > 0 and not await decl.is_checked():
                    await decl.check()
                    log.info("Checked declaration")
            except Exception as e:
                log.warning(f"Declaration checkbox: {e}")

            job_id = job["id"][:6]
            PENDING_BROWSERS[job_id] = {"browser": browser, "page": page, "loop": asyncio.get_running_loop()}
            notify_apply(
                f"Form filled — {job['title']} @ {job['company']}\n"
                f"Cover letter sent above. Scroll through the form on your Mac to verify.\n\n"
                f"YES → submit\n"
                f"NO → cancel"
            )

            while job_id in PENDING_BROWSERS:
                await asyncio.sleep(2)

        # Cover letter file is reused across applies — leave it in place

    asyncio.run(fill())

def _pick_canned_static(question: str, company: str = "") -> str:
    q = question.lower()
    generational = [
        "vast", "varda", "relativity", "muon", "astro mechanica", "rocket lab",
        "boom", "hermeus", "physical intelligence", "figure", "apptronik",
    ]
    if any(x in q for x in ["strength", "excel"]):
        return CANNED_ANSWERS["strength"]
    if any(x in q for x in ["playbook", "ambiguous", "challenge"]):
        return CANNED_ANSWERS["no_playbook"]
    if any(x in q for x in ["why", "interest", "motivation"]):
        return CANNED_ANSWERS["why_here"]
    if any(x in q for x in ["salary", "compensation", "pay"]):
        if any(g in company.lower() for g in generational):
            return CANNED_ANSWERS["salary_generational"]
        return CANNED_ANSWERS["salary"]
    if any(x in q for x in ["start", "available"]):
        return CANNED_ANSWERS["start_date"]
    if any(x in q for x in ["relocat", "move", "remote"]):
        return CANNED_ANSWERS["relocate"]
    if any(x in q for x in ["year", "experience"]):
        return CANNED_ANSWERS["experience_years"]
    return ""

def _ai_answer_static(question: str) -> str:
    try:
        prompt = f"""You are Blaze Renezeder filling out a job application. Answer this question in his voice.
Rules: Direct and confident. No bullet points. No corporate buzzwords. Under 100 words. Sound like a sharp operator.
His background: Operations professional. Partners Bank — million-dollar transactions, zero errors. Beer Girl — ran logistics solo. Rejigg — autonomous M&A pipeline. Built AI agent from scratch with no coding background. Eagle Scout. Student pilot. Taekwondo black belt.
Question: {question}"""
        client = Anthropic(api_key=CLAUDE_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception:
        return ""

def _exceeds_experience(text: str, max_years: int = 4) -> bool:
    """Return True if description explicitly requires more years than candidate has."""
    import re
    # Match patterns like "5+ years", "7 to 10 years", "10 years of experience"
    matches = re.findall(
        r'(\d+)\s*(?:\+|to\s*\d+)?\s*years?\s+(?:of\s+)?(?:relevant\s+|related\s+|professional\s+)?experience',
        text.lower()
    )
    for m in matches:
        if int(m) > max_years:
            return True
    return False

def basic_filter(job: dict) -> bool:
    title = job["title"].lower()
    combined = (job["title"] + " " + job["description"]).lower()
    if any(k in combined for k in EXCLUDE_KEYWORDS):
        return False
    # Reject roles requiring more experience than Blaze has (~3 years)
    if _exceeds_experience(combined, max_years=4):
        return False
    # For structured sources (Greenhouse, Lever, Ashby), require keyword in title
    if job.get("source") in ("greenhouse", "lever", "ashby"):
        if not any(k in title for k in ROLE_KEYWORDS):
            return False
    else:
        if not any(k in combined for k in ROLE_KEYWORDS):
            return False
    strict_loc = job.get("source") in ("greenhouse", "lever", "ashby")
    if not is_bay_area(job.get("location", ""), strict=strict_loc):
        return False
    if not salary_ok(job):
        return False
    return True

# ── AI scoring ────────────────────────────────────────────────────────────────

def ai_score_jobs(jobs: list) -> list:
    if not jobs:
        return []
    client = Anthropic(api_key=CLAUDE_API_KEY)
    job_list = "\n".join([
        f"JOB {i+1}: {j['title']} at {j['company']} | {j['location']}"
        for i, j in enumerate(jobs[:20])
    ])
    prompt = f"""Score these jobs for this candidate:
{CANDIDATE_PROFILE}

Score each job 1-10. You are not a generic ATS. You think like Blaze.

Ask yourself: would Blaze be genuinely excited to wake up and go to this job?

Score HIGH (7-10) if:
- The company builds something physical that exists in the real world: robots, spacecraft, autonomous vehicles, AI hardware, aerospace, clean energy, physical infrastructure
- Small team, founder-led or close to founders, real ownership not just execution
- Role is ops, coordination, logistics, program management, strategic events, chief of staff, biz ops, deployment, field operations, or launch operations
- Experience requirement is 0-4 years or not listed
- Located in SF, Bay Area, or Peninsula
- Mission is something worth telling people about
- Extra points if the mission moves humanity meaningfully forward: Mars, humanoid robots, clean energy, autonomous transportation at scale

Score MEDIUM (5-6) if:
- Good company but role is slightly off or experience bar is a stretch
- Great role but company is large and bureaucratic
- Right mission but located South Bay or further

Score LOW (1-4) if:
- Requires security clearance, engineering degree, PhD, or 5+ years
- Defense contractor, weapons, classified, surveillance
- Pure software engineering, ML, data science, or research
- Outside Bay Area
- Senior, Staff, Principal, VP, or Director title
- Fortune 500 energy, slow moving, process-heavy
- Anything that causes harm

A high score requires BOTH genuine excitement AND realistic odds of landing it.

Return ONLY valid JSON, no markdown:
[{{"job_index": 1, "score": 8, "reason": "one sentence covering fit and realistic odds"}}]

Jobs:
{job_list}"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        text = response.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        scores = json.loads(text.strip())
        result = []
        for s in scores:
            idx = s["job_index"] - 1
            if 0 <= idx < len(jobs) and s["score"] >= 7:
                jobs[idx]["score"] = s["score"]
                jobs[idx]["reason"] = s["reason"]
                result.append(jobs[idx])
        return result
    except Exception as e:
        log.error(f"AI scoring failed: {e}")
        return jobs[:3]

# ── Enrichment ────────────────────────────────────────────────────────────────

def enrich_job(job: dict) -> dict:
    domain = job.get("domain", "")
    company = job.get("company", "")
    log.info(f"Enriching: {company}")
    job["hiring_manager"] = get_hiring_manager(domain, company) if domain else ""
    job["company_address"] = get_company_address(company)
    if job["hiring_manager"]:
        log.info(f"  Found hiring manager: {job['hiring_manager']}")
    if job["company_address"]:
        log.info(f"  Found address: {job['company_address'].split(chr(10))[0]}")
    return job

# ── Cover letter generation ───────────────────────────────────────────────────

def generate_cover_letter(job: dict) -> str:
    client = Anthropic(api_key=CLAUDE_API_KEY)
    hiring_manager = job.get("hiring_manager", "")
    company_address = job.get("company_address", "")
    greeting = f"Dear {hiring_manager}," if hiring_manager else "Dear Hiring Manager,"
    address_block = f"{company_address}\n\n" if company_address else ""

    prompt = f"""Write a cover letter for this candidate applying to this role. Use ONLY the real experiences in the profile below. Do not invent anything.

CANDIDATE: {CANDIDATE['name']}
APPLYING TO: {job['title']} at {job['company']}

CANDIDATE PROFILE:
{CANDIDATE_PROFILE}

Open exactly with:
{address_block}{greeting}

VOICE AND STYLE — study this carefully:
The letter must sound like the candidate wrote it himself. Specific, vivid, first-person. No corporate language. No bullet points. No dashes as punctuation. No "I am writing to apply." No hedging. Every sentence earns its place. When describing work, use concrete physical and operational detail — not abstract summaries. The reader should feel like they were there.

STRUCTURE — follow this exactly:

Paragraph 1: Why this specific company and role. One to three sentences. Genuine and specific to their mission, not generic enthusiasm.

Paragraph 2: A.R.E.S. and OpenClaw. With no coding or computer science background, the candidate built A.R.E.S. (Autonomous Role Extraction System) — an autonomous agent that sources, screens, and tracks job opportunities, now live on GitHub at https://github.com/blazerenezeder/A.R.E.S. Using OpenClaw, a personal AI operating system he is actively developing, he has introduced three additional agents that run continuously and each handle distinct areas of his life. Every morning he wakes up to a comprehensive report telling him exactly what to action that day. This paragraph should make the reader understand: he identifies problems, teaches himself what is needed, and ships things that work.

Paragraph 3: Rejigg. He owned the full M&A sourcing pipeline at an acquisition marketplace for small businesses — from identifying targets to diligence to close. He personally spoke with thousands of business owners across America, running one-call closes to get them listed where they could field multiple offers. Within his first two weeks he sourced a deal that received a $38 million indication of intent. No playbook. High stakes. Moved fast and earned trust under pressure.

Paragraph 4: Beer Girl. He wore every hat. On any given day: walking on-premise and off-premise accounts across multiple regions selling cans and kegs, then driving to load a Sprinter van with two metric tons of beer using a forklift he learned on the job, hauling hundreds of miles down to San Diego and back, then running a marketing event past midnight. On a strong day he moved through more than fifteen accounts. He owned go-to-market and logistics end-to-end for a founder-led startup.

Paragraph 5: One or two sentences only. Partners Bank (million-dollar transactions, zero compliance errors across eleven months, studied credit memos independently with no finance background). Then Coast Film Festival if relevant (2,500-person event, zero queue delays). Keep this paragraph short — these are supporting proof, not anchors.

Paragraph 6: Close. One or two sentences connecting his background to the team's needs. He wants real ownership, a team close to founders, and a mission that matters. Confident. Not eager-sounding. He is ready to contribute immediately and figure out what needs to be done without being asked.

The letter must close with exactly:
Sincerely,
{CANDIDATE['name']}
{CANDIDATE['email']}
{CANDIDATE['phone']}

Length: 450 to 550 words. No dashes. No bullet points. No invented details. Every sentence specific and earned."""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        log.error(f"Cover letter failed: {e}")
        return "Cover letter generation failed."

# ── WhatsApp ──────────────────────────────────────────────────────────────────

def send_telegram(body: str):
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        chunks = [body[i:i+1500] for i in range(0, len(body), 1500)]
        for chunk in chunks:
            requests.post(url, json={"chat_id": chat_id, "text": chunk})
            time.sleep(1)
        log.info("Telegram sent")
    except Exception as e:
        log.error(f"Telegram failed: {e}")

# Post to #ares-pipeline Slack channel using Maverick's bot token (which has channel post perms).
def send_ares_channel(body: str, channel: str = "#ares-pipeline"):
    try:
        from slack_sdk import WebClient
        slack_token = os.getenv("SLACK_TOKEN_GRIZZ", "")
        if not slack_token:
            return
        WebClient(token=slack_token).chat_postMessage(channel=channel, text=body)
        log.info(f"Slack {channel} sent")
    except Exception as e:
        log.warning(f"Slack {channel} send failed: {e}")

# Notify Blaze about apply-flow progress via Slack #ares-pipeline.
# Telegram disabled 2026-05-15. Set ARES_ENABLE_TELEGRAM=1 to also send via Telegram.
def notify_apply(body: str):
    if os.getenv("ARES_ENABLE_TELEGRAM") == "1":
        send_telegram(body)
    send_ares_channel(body)

def download_telegram_file(file_id: str, suggested_name: str) -> str:
    """Download a Telegram file by file_id into INBOX_DIR. Returns local path or ''."""
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        info = requests.get(
            f"https://api.telegram.org/bot{token}/getFile",
            params={"file_id": file_id}, timeout=30,
        ).json().get("result", {})
        file_path = info.get("file_path")
        if not file_path:
            log.warning("getFile returned no file_path")
            return ""
        os.makedirs(INBOX_DIR, exist_ok=True)
        name = os.path.basename(suggested_name or file_path) or "telegram_upload.bin"
        dest = os.path.join(INBOX_DIR, name)
        if os.path.exists(dest):
            root, ext = os.path.splitext(name)
            dest = os.path.join(INBOX_DIR, f"{root}_{int(time.time())}{ext}")
        with requests.get(
            f"https://api.telegram.org/file/bot{token}/{file_path}",
            stream=True, timeout=120,
        ) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
        return dest
    except Exception as e:
        log.error(f"Telegram file download failed: {e}")
        return ""

# ── Main daily run ────────────────────────────────────────────────────────────

def daily_run():
    lock_file = "/tmp/ares_daily_run.lock"
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
    except FileExistsError:
        log.warning("A.R.E.S. scan already running — skipping duplicate.")
        return
    try:
        _daily_run_inner()
    finally:
        try:
            os.remove(lock_file)
        except Exception:
            pass

def _daily_run_inner():
    log.info("=== A.R.E.S. INITIATING DAILY SCAN ===")
    seen = load_seen()
    all_jobs = fetch_all_jobs()
    new_jobs = [j for j in all_jobs if j["id"] not in seen]
    log.info(f"{len(new_jobs)} new unseen jobs")
    for j in all_jobs:
        seen.add(j["id"])
    save_seen(seen)
    filtered = [j for j in new_jobs if basic_filter(j)]
    log.info(f"{len(filtered)} passed basic filter")
    if not filtered:
        _no_match_msg = f"A.R.E.S. // {datetime.now().strftime('%b %d')}\n\nNo new matching roles found today."
        send_telegram(_no_match_msg)
        try:
            from slack_sdk import WebClient as _WC
            _grizz_token = os.getenv("SLACK_TOKEN_GRIZZ", "")
            if _grizz_token:
                _WC(token=_grizz_token).chat_postMessage(channel="#ares-pipeline", text=_no_match_msg)
        except Exception as _e:
            log.warning(f"Slack post failed: {_e}")
        return
    top_jobs = ai_score_jobs(filtered)
    log.info(f"{len(top_jobs)} passed AI scoring")
    if not top_jobs:
        _no_match_msg = f"A.R.E.S. // {datetime.now().strftime('%b %d')}\n\nFound {len(filtered)} roles but none cleared the match threshold."
        send_telegram(_no_match_msg)
        try:
            from slack_sdk import WebClient as _WC
            _grizz_token = os.getenv("SLACK_TOKEN_GRIZZ", "")
            if _grizz_token:
                _WC(token=_grizz_token).chat_postMessage(channel="#ares-pipeline", text=_no_match_msg)
        except Exception as _e:
            log.warning(f"Slack post failed: {_e}")
        return
    pending = load_pending()
    new_pending = []
    for job in top_jobs[:4]:
        job = enrich_job(job)
        cover = generate_cover_letter(job)
        entry = {
            "id": job["id"],
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "link": job["link"],
            "score": job.get("score", "?"),
            "reason": job.get("reason", ""),
            "hiring_manager": job.get("hiring_manager", ""),
            "company_address": job.get("company_address", ""),
            "cover_letter": cover,
            "status": "pending",
            "found_at": datetime.now().isoformat()
        }
        new_pending.append(entry)
        pending.append(entry)
        time.sleep(1)
    save_pending(pending)
    date_str = datetime.now().strftime("%b %d")
    msg = f"A.R.E.S. // {date_str}\n{len(new_pending)} role(s) acquired:\n\n"
    for i, job in enumerate(new_pending):
        hm = f" | Contact: {job['hiring_manager']}" if job.get("hiring_manager") else ""
        salary = format_salary(job)
        date_flag = job.get("date_flag", "")
        msg += f"#{i+1} {job['title']}\n"
        msg += f"   {job['company']} | {job['location']}{hm}\n"
        msg += f"   {salary}\n"
        msg += f"   Score: {job['score']}/10 — {job['reason']}\n"
        if date_flag:
            msg += f"   {date_flag}\n"
        msg += f"   {job['link']}\n\n"
    msg += "YES → apply next  |  NO → skip  |  CL → cover letter"
    send_telegram(msg)
    # Also post to Slack #ares-pipeline and #morning-brief
    try:
        from slack_sdk import WebClient as _WC
        _grizz_token = os.getenv("SLACK_TOKEN_GRIZZ", "")
        if _grizz_token:
            _wc = _WC(token=_grizz_token)
            _wc.chat_postMessage(channel="#ares-pipeline", text=msg)
            _wc.chat_postMessage(channel="#morning-brief", text=msg)
    except Exception as _e:
        log.warning(f"Slack post failed: {_e}")
    log.info(f"A.R.E.S. scan complete. {len(new_pending)} roles sent.")

# ── Webhook server ────────────────────────────────────────────────────────────

import threading

def forward_to_openclaw(message: str) -> str:
    """Forward a freeform Telegram message to OpenClaw's main agent (Maverick)."""
    message = (message or "").strip()
    if not message:
        return ""
    try:
        result = subprocess.run(
            ["openclaw", "agent", "--agent", "main",
             "--message", message, "--json", "--timeout", "120"],
            capture_output=True, text=True, timeout=150,
        )
    except subprocess.TimeoutExpired:
        log.warning("openclaw agent timed out")
        return "Maverick is taking too long to respond. Try again."
    except FileNotFoundError:
        log.warning("openclaw CLI not found on PATH")
        return "Maverick unavailable: openclaw CLI not on PATH."
    except Exception as e:
        log.warning(f"openclaw agent invocation failed: {e}")
        return f"Maverick call failed: {e}"

    stdout = result.stdout or ""
    brace = stdout.find("{")
    if brace < 0:
        err_excerpt = (result.stderr or stdout).strip().splitlines()[0] if (result.stderr or stdout).strip() else ""
        log.warning(f"openclaw agent: no JSON in output (exit {result.returncode}): "
                    f"{(result.stderr or stdout)[:200]}")
        return f"Maverick unreachable: {err_excerpt[:200]}" if err_excerpt else "Maverick unreachable (no output)."
    try:
        data = json.loads(stdout[brace:])
    except json.JSONDecodeError as e:
        log.warning(f"openclaw agent: JSON parse failed: {e}")
        return "Maverick response unreadable."

    # OpenClaw wraps the agent response in a "result" object now.
    # Accept both shapes so this keeps working if the wrapper is removed.
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


# Pilot-speak: natural-language synonyms for YES/NO/CL. Match the user's vibe.
_PILOT_YES = {
    "YES", "YEP", "YEAH", "Y", "GO", "GO HOT", "CLEARED", "CLEARED HOT",
    "YOU'RE CLEARED", "YOURE CLEARED", "WE'RE CLEARED", "WERE CLEARED",
    "SEND IT", "SEND", "WEAPONS FREE", "FIRE", "FIRE AT WILL",
    "APPROVE", "APPROVED", "DO IT", "SHIP IT", "ROGER", "ROGER THAT",
    "AFFIRMATIVE", "COPY THAT", "HIT IT", "LETS GO", "LET'S GO",
    "GREEN LIGHT", "GREENLIT",
}
_PILOT_NO = {
    "NO", "NOPE", "NAH", "N", "NEGATIVE", "ABORT", "RTB", "STAND DOWN",
    "SCRUB", "NO GO", "PASS", "SKIP", "REJECT", "REJECTED",
    "NEGATIVE GHOST RIDER", "HOLD UP", "NEVER MIND", "NEVERMIND",
}
_PILOT_CL = {
    "CL", "COVER LETTER", "LETTER", "SHOW LETTER", "PREVIEW LETTER",
    "SHOW ME THE LETTER", "SHOW ME THE COVER LETTER", "READ ME THE LETTER",
    "PREVIEW", "PREVIEW THE LETTER",
}

def _normalize_command(text: str) -> str:
    """Translate pilot-speak to canonical YES/NO/CL/iCL. Returns None if not a command."""
    s = (text or "").strip().upper()
    if not s:
        return None
    if s in _PILOT_YES:
        return "YES"
    if s in _PILOT_NO:
        return "NO"
    if s in _PILOT_CL:
        return "CL"
    if re.match(r"^\d+CL$", s):
        return s
    return None

def handle_command(body, pending):
    changed = False
    response_text = ""
    original = (body or "").strip()
    body = _normalize_command(original) or original.upper()

    # YES / NO when a form is open on screen
    if body == "YES" and PENDING_BROWSERS:
        job_id = next(iter(PENDING_BROWSERS))
        page = PENDING_BROWSERS[job_id]["page"]
        browser = PENDING_BROWSERS[job_id]["browser"]
        loop = PENDING_BROWSERS[job_id]["loop"]
        import asyncio
        async def do_submit():
            try:
                await page.click("button[type=submit]")
                await page.wait_for_timeout(2000)
                notify_apply("Submitted. Good luck.")
            except Exception as e:
                notify_apply(f"Submit failed: {e}")
            finally:
                await browser.close()
                if job_id in PENDING_BROWSERS:
                    del PENDING_BROWSERS[job_id]
        try:
            asyncio.run_coroutine_threadsafe(do_submit(), loop).result(timeout=30)
        except Exception as e:
            notify_apply(f"Submit error: {e}")
        return changed, response_text

    if body == "NO" and PENDING_BROWSERS:
        job_id = next(iter(PENDING_BROWSERS))
        loop = PENDING_BROWSERS[job_id]["loop"]
        import asyncio
        async def do_cancel():
            await PENDING_BROWSERS[job_id]["browser"].close()
            if job_id in PENDING_BROWSERS:
                del PENDING_BROWSERS[job_id]
        try:
            asyncio.run_coroutine_threadsafe(do_cancel(), loop).result(timeout=10)
        except Exception as e:
            log.warning(f"Cancel error: {e}")
        response_text = "Cancelled. Next?"
        return changed, response_text

    # YES / NO when no form is open — approve or skip next queued job
    if body == "YES":
        for job in pending:
            if job["status"] == "pending":
                job["status"] = "approved"
                changed = True
                if is_ashby_job(job):
                    t = threading.Thread(target=ashby_apply, args=(job,), daemon=True)
                    t.start()
                    response_text = f"Goose on it — opening Ashby form for {job['title']} at {job['company']}..."
                elif is_greenhouse_job(job):
                    t = threading.Thread(target=greenhouse_apply, args=(job,), daemon=True)
                    t.start()
                    response_text = f"Goose on it — opening Greenhouse form for {job['title']} @ {job['company']}..."
                else:
                    response_text = (
                        f"Manual apply — {job['title']} @ {job['company']}\n"
                        f"{job['link']}\n\n"
                        f"Name: {CANDIDATE['name']}\n"
                        f"Email: {CANDIDATE['email']}\n"
                        f"Phone: {CANDIDATE['phone']}\n"
                        f"LinkedIn: {CANDIDATE['linkedin']}\n\n"
                        f"Reply CL for cover letter."
                    )
                break
        else:
            response_text = "No pending jobs in queue."
        return changed, response_text

    if body == "NO":
        for job in pending:
            if job["status"] == "pending":
                job["status"] = "skipped"
                changed = True
                response_text = f"Skipped {job['title']}. Next?"
                break
        else:
            response_text = "No pending jobs to skip."
        return changed, response_text

    if body == "CL":
        for job in pending:
            if job["status"] == "pending":
                response_text = f"Cover Letter — {job['title']} @ {job['company']}\n\n{job['cover_letter']}"
                break
        else:
            response_text = "No pending jobs."
        return changed, response_text

    for i in range(1, 8):
        if body == f"{i}CL":
            idx = i - 1
            if idx < len(pending):
                job = pending[idx]
                response_text = f"Cover Letter — {job['title']} @ {job['company']}\n\n{job['cover_letter']}"
            break
    else:
        # Not a recognized job command — forward to OpenClaw's main agent (Maverick)
        response_text = forward_to_openclaw(original)

    return changed, response_text

def poll_telegram():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    offset = 0
    log.info("Telegram polling started...")
    while True:
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": offset, "timeout": 30},
                timeout=35
            )
            updates = r.json().get("result", [])
            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "").strip()
                caption = (msg.get("caption") or "").strip()
                document = msg.get("document")
                from_id = str(msg.get("from", {}).get("id", ""))
                if from_id != chat_id:
                    continue

                if document:
                    fname = document.get("file_name") or "upload.bin"
                    log.info(f"Telegram document: {fname}")
                    dest = download_telegram_file(document["file_id"], fname)
                    if not dest:
                        send_telegram(f"Failed to save {fname}.")
                        continue
                    send_telegram(f"Got file: {os.path.basename(dest)}")
                    synth = f"[User uploaded file: {os.path.basename(dest)} at {dest}]"
                    if caption:
                        synth += f"\nCaption: {caption}"
                    pending = load_pending()
                    changed, response = handle_command(synth, pending)
                    if changed:
                        save_pending(pending)
                    if response:
                        send_telegram(response)
                    continue

                log.info(f"Telegram command: {text}")
                pending = load_pending()
                changed, response = handle_command(text, pending)
                if changed:
                    save_pending(pending)
                if response:
                    send_telegram(response)
        except Exception as e:
            log.error(f"Polling error: {e}")
            time.sleep(5)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    log.info("A.R.E.S. — Autonomous Role Extraction System — ONLINE")
    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        # Telegram polling disabled 2026-05-15 — Slack is the primary channel.
        # Set ARES_ENABLE_TELEGRAM=1 to re-enable.
        if os.getenv("ARES_ENABLE_TELEGRAM") == "1":
            log.info("DAEMON MODE — Telegram polling ENABLED via env var.")
            t = threading.Thread(target=poll_telegram, daemon=True)
            t.start()
        else:
            log.info("DAEMON MODE — Telegram polling DISABLED (Slack only). Idle loop.")
        while True:
            time.sleep(60)
    else:
        log.info("Running scan...")
        daily_run()
