#!/usr/bin/env python3
"""
gmail_freelance_digest.py
=========================

Reads the Gmail inbox, isolates emails from freelancer / job platforms,
scores each against Parth's relevance profile (references/freelance-filter.md),
posts the relevant ones to a Discord webhook, then archives them.

Design notes
------------
- Reuses the Google OAuth refresh-token flow from scripts/google_auth_helper.py
  (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN in .env).
- "Archive" = remove the INBOX label. Mail is NEVER deleted.
- Idempotent: processed message IDs are cached so re-runs never double-post.
- Dry-run by default. Use --post to actually send to Discord + archive.

Usage
-----
  python scripts/gmail_freelance_digest.py            # dry-run, print what it would do
  python scripts/gmail_freelance_digest.py --post     # send to Discord + archive
  python scripts/gmail_freelance_digest.py --limit 20 # only look at 20 messages
  python scripts/gmail_freelance_digest.py --threshold 5
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
import urllib.parse
import base64
import email
from email.header import decode_header
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
CACHE_PATH = SCRIPT_DIR / ".freelance_digest_cache.json"
FILTER_PATH = ROOT_DIR / "references" / "freelance-filter.md"

# Freelancer / job-platform sender domains
SENDER_DOMAINS = [
    "upwork.com", "fiverr.com", "freelancer.com", "linkedin.com",
    "indeed.com", "toptal.com", "guru.com", "peopleperhour.com",
    "simplyhired.com", "flexjobs.com", "wellfound.com",
]

# ---------------------------------------------------------------------------
# .env helper (mirrors google_auth_helper.py)
# ---------------------------------------------------------------------------
def get_env_var(var_name):
    val = os.getenv(var_name)
    if val:
        return val
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{var_name}="):
                parts = line.strip().split("=", 1)
                if len(parts) > 1:
                    val = parts[1].strip()
                    if (val.startswith('"') and val.endswith('"')) or \
                       (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    return val
    return ""


# ---------------------------------------------------------------------------
# Google token (refresh -> access)
# ---------------------------------------------------------------------------
def get_access_token():
    client_id = get_env_var("GOOGLE_CLIENT_ID")
    client_secret = get_env_var("GOOGLE_CLIENT_SECRET")
    refresh_token = get_env_var("GOOGLE_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        print("ERROR: Missing GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_REFRESH_TOKEN in .env")
        print("Run: python scripts/google_auth_helper.py  (already done if those exist)")
        sys.exit(1)

    token_url = "https://oauth2.googleapis.com/token"
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode("utf-8")
    req = urllib.request.Request(
        token_url, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8")).get("access_token")
    except urllib.error.HTTPError as e:
        print(f"ERROR exchanging refresh token: {e.code} {e.reason}")
        print(e.read().decode("utf-8", errors="ignore"))
        sys.exit(1)


def gmail_get(token, url):
    req = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def gmail_post(token, url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }, method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return resp.read().decode("utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Relevance profile (parsed from references/freelance-filter.md)
# ---------------------------------------------------------------------------
def _add_keywords(target_set, text):
    """Parse a line that may be a bullet list or comma-separated inline list."""
    text = text.strip()
    if text.startswith("- "):
        text = text[2:]
    # split on commas and bullets
    for part in text.replace("\n", ",").split(","):
        kw = part.strip().strip('"').strip("'").lower()
        # drop trailing markdown bullets / stray chars
        kw = kw.lstrip("- ").strip()
        if kw and kw not in ("each",):
            target_set.add(kw)


def load_filter():
    strong, soft, exclude, threshold, gig_signals, downweight = (
        set(), set(), set(), 5, set(), set()
    )
    current = None
    if FILTER_PATH.exists():
        for raw in FILTER_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip().lstrip("#").strip()
            low = line.lower()
            # Any heading resets the current section (so prose/bullets under
            # unrelated sections are never captured).
            if raw.strip().startswith("#"):
                current = None
            if low.startswith("strong_keywords"):
                # keywords may follow on same line after the colon
                rest = line.split(":", 1)[1] if ":" in line else ""
                if rest.strip():
                    _add_keywords(strong, rest)
                current = "strong"; continue
            if low.startswith("soft_keywords"):
                rest = line.split(":", 1)[1] if ":" in line else ""
                if rest.strip():
                    _add_keywords(soft, rest)
                current = "soft"; continue
            if low.startswith("exclude_keywords"):
                rest = line.split(":", 1)[1] if ":" in line else ""
                if rest.strip():
                    _add_keywords(exclude, rest)
                current = "exclude"; continue
            if low.startswith("gig signal"):
                rest = line.split(":", 1)[1] if ":" in line else ""
                if rest.strip():
                    _add_keywords(gig_signals, rest)
                current = "gig"; continue
            if low.startswith("downweight_keywords"):
                rest = line.split(":", 1)[1] if ":" in line else ""
                if rest.strip():
                    _add_keywords(downweight, rest)
                current = "down"; continue
            if low.startswith("threshold"):
                try:
                    threshold = int(line.split("=")[1].strip())
                except Exception:
                    pass
                current = None; continue
            if not line or line.startswith("#"):
                continue
            # continuation lines: only bullet lists ("- item") belong to the
            # current section. Inline comma lists are handled on the heading
            # line itself, so prose paragraphs are never captured.
            if current and line.startswith("- "):
                _add_keywords(
                    strong if current == "strong" else
                    soft if current == "soft" else
                    exclude if current == "exclude" else
                    gig_signals if current == "gig" else downweight, line
                )
    return strong, soft, exclude, threshold, gig_signals, downweight


def has_gig_signal(text, gig_signals):
    """True if the mail contains at least one genuine freelance gig signal."""
    text_l = text.lower()
    return any(s in text_l for s in gig_signals)


def score_email(text, strong, soft, exclude, downweight=None):
    if downweight is None:
        downweight = set()
    text_l = text.lower()
    score = 0
    matched = []
    for kw in strong:
        if kw in text_l:
            score += 3
            matched.append(kw)
    for kw in soft:
        if kw in text_l:
            score += 1
            matched.append(kw)
    for kw in exclude:
        if kw in text_l:
            score -= 5
            matched.append(f"EXCLUDE:{kw}")
    for kw in downweight:
        if kw in text_l:
            score -= 3
            matched.append(f"DOWN:{kw}")
    return score, matched


# ---------------------------------------------------------------------------
# Project extraction
# ---------------------------------------------------------------------------
# Freelancer.com digest emails list multiple projects in a repeatable shape:
#   <Title>
#   Budget: <...>
#   Skills: <comma list>
#   Description:
#   <text>
#   /projects/<slug>.html?<tracking>
# We parse each into a structured dict so we can score/select individual
# projects instead of dumping the whole email body to Discord.
def parse_projects(body, base_url="https://www.freelancer.com"):
    """Extract individual project listings from a freelancer digest email.

    Returns a list of dicts: {title, budget, skills, description, url}.
    If the email isn't a recognizable multi-project digest, returns [].
    """
    projects = []
    # Split on project URL lines (the /projects/... marker starts each block)
    import re
    # Find all /projects/... or /jobs/... or /contests/... URLs as anchors
    url_re = re.compile(r"(/(?:projects|jobs|contests)/[^\s]+\.html[^\s]*)")
    matches = list(url_re.finditer(body))
    if not matches:
        return projects

    for i, m in enumerate(matches):
        url_path = m.group(1).split("?")[0]
        url = base_url + url_path
        # The block for this project is the text BEFORE this URL, after the
        # previous URL (or start of body).
        start = matches[i - 1].end() if i > 0 else 0
        end = m.start()
        block = body[start:end]

        # Title = first non-empty line of the block
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        title = lines[0] if lines else "(untitled)"
        # Skip blocks whose "title" is actually a URL / logo / boilerplate
        if title.lower().startswith("http") or "freelancer.com" in title.lower() \
           or title.lower().startswith("here are the latest"):
            continue

        # Budget line
        budget = ""
        for ln in lines:
            if ln.lower().startswith("budget:"):
                budget = ln[len("budget:"):].strip()
                break

        # Skills line
        skills = ""
        for ln in lines:
            if ln.lower().startswith("skills:"):
                skills = ln[len("skills:"):].strip()
                break

        # Description = text after "Description:" up to the URL
        desc = ""
        di = block.lower().find("description:")
        if di != -1:
            desc = block[di + len("description:"):].strip()

        projects.append({
            "title": title,
            "budget": budget,
            "skills": skills,
            "description": desc,
            "url": url,
        })
    # Dedupe by URL (digests may list a project in both Projects + Contests)
    seen = set()
    deduped = []
    for p in projects:
        if p["url"] in seen:
            continue
        seen.add(p["url"])
        deduped.append(p)
    return deduped


def score_project(proj, strong, soft, exclude, downweight=None):
    """Score a single extracted project (title + skills + description)."""
    text = f"{proj['title']}\n{proj['skills']}\n{proj['description']}"
    return score_email(text, strong, soft, exclude, downweight)


# Content signals that mark an email as "freelancer / gig / job" related,
# even when it comes from a personal address (not a platform domain).
FREELANCER_CONTENT_SIGNALS = [
    "freelance", "freelancer", "upwork", "fiverr", "contract", "contractual",
    "hiring", "hire you", "job offer", "project for you", "remote position",
    "part-time role", "gig", "outsource", "outsourcing", "looking for a developer",
    "looking for someone", "paid project", "budget", "rate", "per hour",
    "fixed price", "milestone", "proposal", "bid", "talent", "recruiter",
    "we'd like to offer", "we are looking for", "can you help us build",
    "need a developer", "need an engineer", "side project", "consulting",
]


def is_freelancer_mail(from_addr, subject, body, sender_domains):
    """True if the mail looks like freelancer/job mail.

    Matches on EITHER a known platform sender domain OR strong content
    signals, so direct freelancer emails (personal domains) are NOT skipped.
    """
    from_domain = from_addr.lower().split("@")[-1].strip(">").strip()
    if any(d in from_domain for d in sender_domains):
        return True
    haystack = (subject + "\n" + body).lower()
    hits = sum(1 for s in FREELANCER_CONTENT_SIGNALS if s in haystack)
    return hits >= 2  # require >=2 signals to avoid false positives from one word


# ---------------------------------------------------------------------------
# Email parsing helpers
# ---------------------------------------------------------------------------
def decode_mime(s):
    if not s:
        return ""
    out = []
    for part, enc in decode_header(s):
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            out.append(part)
    return "".join(out)


def get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode("utf-8", errors="ignore")
                except Exception:
                    return ""
        # fallback: first part
        try:
            return msg.get_payload(0).get_payload(decode=True).decode("utf-8", errors="ignore")
        except Exception:
            return ""
    try:
        return msg.get_payload(decode=True).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def snippet(text, n=400):
    text = " ".join(text.split())
    return text[:n] + ("…" if len(text) > n else "")


def safe(s):
    """Make a string safe to print on the Windows console (CP1252)."""
    if not isinstance(s, str):
        s = str(s)
    enc = (sys.stdout.encoding or "utf-8")
    return s.encode(enc, "ignore").decode(enc, "ignore")


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------
def post_project_to_discord(webhook, proj, sender, score, matched, gmail_link):
    """Post a single extracted project as a Discord embed."""
    content = {
        "embeds": [{
            "title": proj["title"][:256] or "(untitled project)",
            "color": 0x2ECC71 if score >= 5 else 0xF1C40F,
            "fields": [
                {"name": "Budget", "value": proj["budget"][:256] or "—", "inline": True},
                {"name": "Relevance", "value": str(score), "inline": True},
                {"name": "Skills", "value": proj["skills"][:1024] or "—", "inline": False},
                {"name": "Description", "value": snippet(proj["description"], 600) or "—", "inline": False},
                {"name": "Links", "value": f"[Project]({proj['url']}) • [Gmail]({gmail_link})", "inline": False},
            ],
            "footer": {"text": f"Freelance digest • matched: {', '.join(matched[:8]) or '—'}"},
        }]
    }
    data = json.dumps(content).encode("utf-8")
    req = urllib.request.Request(webhook, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "freelance-digest/1.0 (+https://github.com/nateherkai/AIS-OS)")
    try:
        urllib.request.urlopen(req).read()
        return True
    except urllib.error.HTTPError as e:
        print(f"  Discord post failed: {e.code} {e.reason}")
        return False


def post_email_to_discord(webhook, subject, sender, score, matched, body, link):
    """Fallback: post the whole email (used when no structured projects found)."""
    content = {
        "embeds": [{
            "title": subject[:256] or "(no subject)",
            "color": 0x2ECC71 if score >= 5 else 0xF1C40F,
            "fields": [
                {"name": "From", "value": sender[:256], "inline": True},
                {"name": "Relevance", "value": str(score), "inline": True},
                {"name": "Matched", "value": ", ".join(matched[:12]) or "—", "inline": False},
                {"name": "Snippet", "value": snippet(body, 600) or "—", "inline": False},
                {"name": "Open in Gmail", "value": f"[View]({link})", "inline": False},
            ],
            "footer": {"text": "Freelance digest • gmail_freelance_digest.py"},
        }]
    }
    data = json.dumps(content).encode("utf-8")
    req = urllib.request.Request(webhook, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "freelance-digest/1.0 (+https://github.com/nateherkai/AIS-OS)")
    try:
        urllib.request.urlopen(req).read()
        return True
    except urllib.error.HTTPError as e:
        print(f"  Discord post failed: {e.code} {e.reason}")
        return False


# ---------------------------------------------------------------------------
# Cache (idempotency)
# ---------------------------------------------------------------------------
def load_cache():
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed": []}


def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Gmail freelance digest -> Discord + archive")
    ap.add_argument("--post", action="store_true",
                    help="Actually send to Discord and archive. Default is dry-run.")
    ap.add_argument("--limit", type=int, default=50,
                    help="Max messages to scan (default 50).")
    ap.add_argument("--threshold", type=int, default=None,
                    help="Override relevance threshold from filter file.")
    ap.add_argument("--reset-cache", action="store_true",
                    help="Delete the processed-message cache and re-scan all mail.")
    args = ap.parse_args()

    if args.reset_cache:
        if CACHE_PATH.exists():
            CACHE_PATH.unlink()
            print(f"Cache cleared: {CACHE_PATH}")
        else:
            print("No cache file to clear.")

    strong, soft, exclude, threshold, gig_signals, downweight = load_filter()
    if args.threshold is not None:
        threshold = args.threshold

    webhook = get_env_var("DISCORD_WEBHOOK_URL")
    if args.post and not webhook:
        print("ERROR: --post requires DISCORD_WEBHOOK_URL in .env")
        sys.exit(1)

    print(f"[{'POST MODE' if args.post else 'DRY RUN'}] threshold={threshold} limit={args.limit}")
    token = get_access_token()
    cache = load_cache()
    processed = set(cache.get("processed", []))

    # List recent INBOX messages
    url = (f"https://gmail.googleapis.com/gmail/v1/users/me/messages"
           f"?maxResults={args.limit}&labelIds=INBOX")
    try:
        listing = gmail_get(token, url)
    except urllib.error.HTTPError as e:
        print(f"ERROR listing messages: {e.code} {e.reason}")
        print(e.read().decode("utf-8", errors="ignore"))
        sys.exit(1)

    messages = listing.get("messages", [])
    print(f"Scanning {len(messages)} inbox messages...")

    posted = 0
    archived = 0
    skipped_seen = 0

    for m in messages:
        mid = m["id"]
        if mid in processed:
            skipped_seen += 1
            continue

        # NOTE: the list query above uses labelIds=INBOX, so archived / spam /
        # trash mail is NEVER returned here. No client-side INBOX guard needed
        # (the list resource omits labelIds anyway). Archived mail is safe.

        meta = gmail_get(token, f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}?format=metadata&metadataHeaders=From&metadataHeaders=Subject")
        headers = {h["name"]: h["value"] for h in meta.get("payload", {}).get("headers", [])}
        from_addr = headers.get("From", "")
        subject = decode_mime(headers.get("Subject", ""))

        # Fetch full message to read body (needed to detect direct freelancer mail)
        full = gmail_get(token, f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}?format=raw")
        raw = base64.urlsafe_b64decode(full["raw"] + "==")
        msg = email.message_from_bytes(raw)
        body = get_body(msg)

        # Decide if this is freelancer mail: platform domain OR content signals.
        # This ensures direct freelancer emails (personal domains) are NOT skipped.
        if not is_freelancer_mail(from_addr, subject, body, SENDER_DOMAINS):
            # Not freelancer-related -> skip, but cache so we don't rescan it.
            processed.add(mid)
            continue

        # Option B: require at least one genuine gig signal, otherwise skip
        # (filters newsletters, LinkedIn invites, internship alerts, etc.)
        if not has_gig_signal(subject + "\n" + from_addr + "\n" + body, gig_signals):
            print(f"  [no-gig-signal] {safe(subject[:60])}")
            processed.add(mid)
            continue

        link = f"https://mail.google.com/mail/u/0/#inbox/{mid}"

        # Extract individual projects from the email (Freelancer.com digests
        # contain many). If none parsed, fall back to the whole email.
        projects = parse_projects(body)
        mail_score, mail_matched = score_email(
            subject + "\n" + from_addr + "\n" + body, strong, soft, exclude, downweight
        )

        if projects:
            # Score + select only relevant projects from this digest.
            selected = []
            for p in projects:
                ps, pm = score_project(p, strong, soft, exclude, downweight)
                if ps >= threshold:
                    selected.append((p, ps, pm))
            if selected:
                print(f"  [RELEVANT {len(selected)}/{len(projects)} projects] {safe(subject[:50])}  <- {safe(from_addr)}")
                if args.post:
                    for p, ps, pm in selected:
                        if post_project_to_discord(webhook, p, from_addr, ps, pm, link):
                            posted += 1
                    # Archive the whole digest email once (non-destructive)
                    gmail_post(
                        token,
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}/modify",
                        {"removeLabelIds": ["INBOX"]}
                    )
                    archived += 1
                    print(f"    -> posted {len(selected)} project(s) to Discord + archived email")
                else:
                    for p, ps, pm in selected:
                        print(f"    -> would post: {safe(p['title'][:55])} (score {ps})")
            else:
                print(f"  [skip {mail_score}] no relevant projects in digest ({len(projects)} total)")
        else:
            # No structured projects -> score the whole email and post as fallback.
            if mail_score >= threshold:
                print(f"  [RELEVANT {mail_score}] {safe(subject[:60])}  <- {safe(from_addr)}")
                if args.post:
                    if post_email_to_discord(webhook, subject, from_addr, mail_score, mail_matched, body, link):
                        posted += 1
                    gmail_post(
                        token,
                        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}/modify",
                        {"removeLabelIds": ["INBOX"]}
                    )
                    archived += 1
                    print(f"    -> posted email to Discord + archived")
                else:
                    print(f"    -> would post email to Discord + archive (dry-run)")
            else:
                print(f"  [skip {mail_score}] {safe(subject[:60])}")

        processed.add(mid)
        time.sleep(0.1)  # be polite to the API

    cache["processed"] = list(processed)
    save_cache(cache)

    print(f"\nDone. posted={posted} archived={archived} skipped_already_seen={skipped_seen}")
    if not args.post:
        print("This was a dry-run. Re-run with --post to actually send + archive.")


if __name__ == "__main__":
    main()
