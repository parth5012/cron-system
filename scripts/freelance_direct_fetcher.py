#!/usr/bin/env python3
"""
freelance_direct_fetcher.py
===========================

Fetches recent project postings directly from freelance/internship platforms
(Freelancer.com RSS, Upwork RSS, Truelancer RSS, and Internshala scraping),
scores them against Parth's relevance profile (references/freelance-filter.md),
posts relevant ones to Discord, and caches processed URLs.
"""

import os
import sys
import json
import time
import argparse
import urllib.request
import urllib.error
import urllib.parse
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
CACHE_PATH = SCRIPT_DIR / ".freelance_digest_cache.json"
FILTER_PATH = ROOT_DIR / "references" / "freelance-filter.md"

# ---------------------------------------------------------------------------
# Env Helper
# ---------------------------------------------------------------------------
def get_env_var(var_name):
    val = os.getenv(var_name)
    if val:
        return val
    # Fallback to local .env
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{var_name}="):
                parts = line.strip().split("=", 1)
                if len(parts) == 2:
                    v = parts[1].strip()
                    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                        v = v[1:-1]
                    return v
    return None

# ---------------------------------------------------------------------------
# Filter Loader
# ---------------------------------------------------------------------------
def _add_keywords(target_set, text):
    text = text.strip()
    if text.startswith("-"):
        text = text[1:]
    parts = text.replace("\n", ",").split(",")
    for part in parts:
        kw = part.strip().strip('"').strip("'").lower()
        if kw.startswith("-"):
            kw = kw[1:].strip()
        if kw and kw not in ("each",):
            target_set.add(kw)

def load_filter():
    strong, soft, exclude = set(), set(), set()
    threshold = 3
    
    if FILTER_PATH.exists():
        raw = FILTER_PATH.read_text(encoding="utf-8").splitlines()
        current = None
        for line in raw:
            line_strip = line.strip().lstrip("#").strip()
            low = line_strip.lower()
            
            if line.strip().startswith("#"):
                current = None
            
            if low.startswith("strong_keywords"):
                rest = line.split(":", 1)[1] if ":" in line else ""
                _add_keywords(strong, rest)
                current = "strong"
                continue
            elif low.startswith("soft_keywords"):
                rest = line.split(":", 1)[1] if ":" in line else ""
                _add_keywords(soft, rest)
                current = "soft"
                continue
            elif low.startswith("exclude_keywords"):
                rest = line.split(":", 1)[1] if ":" in line else ""
                _add_keywords(exclude, rest)
                current = "exclude"
                continue
            elif low.startswith("threshold"):
                try:
                    threshold = int(line.split("=")[1].strip())
                except Exception:
                    pass
                current = None
                continue
            
            if not line_strip or line.startswith("#"):
                continue
                
            if current and line.strip().startswith("-"):
                if current == "strong":
                    _add_keywords(strong, line)
                elif current == "soft":
                    _add_keywords(soft, line)
                elif current == "exclude":
                    _add_keywords(exclude, line)
                    
    return strong, soft, exclude, threshold

# ---------------------------------------------------------------------------
# Scoring Logic
# ---------------------------------------------------------------------------
def score_project(proj, strong, soft, exclude):
    text = f"{proj.get('title', '')}\n{proj.get('skills', '')}\n{proj.get('description', '')}".lower()
    score = 0
    matched = []
    
    for kw in strong:
        if kw in text:
            score += 3
            matched.append(kw)
    for kw in soft:
        if kw in text:
            score += 1
            matched.append(kw)
    for kw in exclude:
        if kw in text:
            score -= 5
            matched.append(f"EXCLUDE:{kw}")
            
    return score, matched

# ---------------------------------------------------------------------------
# HTML Cleaning
# ---------------------------------------------------------------------------
def clean_html(text):
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

# ---------------------------------------------------------------------------
# Crawling / Fetching
# ---------------------------------------------------------------------------

def fetch_rss_feed(url):
    """Fetches and parses an RSS feed URL, returning a list of job dicts."""
    print(f"Fetching RSS feed from: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
    except Exception as e:
        print(f"Error fetching RSS {url}: {e}")
        return []
    
    # Try parsing XML. If it fails due to malformed XML, fall back to regex.
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(data)
        items = []
        for item in root.findall(".//item"):
            title = item.find("title")
            link = item.find("link")
            desc = item.find("description")
            items.append({
                "title": title.text if title is not None else "",
                "url": link.text if link is not None else "",
                "description": clean_html(desc.text) if desc is not None else "",
                "skills": "",
                "budget": "N/A"
            })
        return items
    except Exception:
        # Regex fallback for RSS parsing
        items = []
        # Convert bytes to string
        text = data.decode("utf-8", errors="ignore")
        item_blocks = re.findall(r'<item>(.*?)</item>', text, re.DOTALL)
        for block in item_blocks:
            title_m = re.search(r'<title>(.*?)</title>', block, re.DOTALL)
            link_m = re.search(r'<link>(.*?)</link>', block, re.DOTALL)
            desc_m = re.search(r'<description>(.*?)</description>', block, re.DOTALL)
            
            title = title_m.group(1).strip() if title_m else ""
            link = link_m.group(1).strip() if link_m else ""
            desc = desc_m.group(1).strip() if desc_m else ""
            
            # Strip CDATA if present
            if title.startswith("<![CDATA["):
                title = title[9:-3]
            if link.startswith("<![CDATA["):
                link = link[9:-3]
            if desc.startswith("<![CDATA["):
                desc = desc[9:-3]
                
            items.append({
                "title": title,
                "url": link,
                "description": clean_html(desc),
                "skills": "",
                "budget": "N/A"
            })
        return items

def scrape_internshala(keywords):
    """Scrapes Internshala for relevant internships."""
    jobs = []
    seen_ids = set()
    
    for kw in keywords:
        url = f"https://internshala.com/internships/keywords-{kw}/"
        print(f"Scraping Internshala for '{kw}': {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            print(f"Error scraping Internshala for {kw}: {e}")
            continue
            
        pattern = r'(id="individual_internship_(\d+)".*?)(?=id="individual_internship_|\Z)'
        blocks = re.findall(pattern, html, re.DOTALL)
        
        for block_html, inst_id in blocks:
            if inst_id in seen_ids:
                continue
            seen_ids.add(inst_id)
            
            # Title
            title_m = re.search(r'class="job-title-href"[^>]*>(.*?)</a>', block_html)
            title = title_m.group(1).strip() if title_m else "Unknown Title"
            
            # Link
            link_m = re.search(r'href="(/internship/detail/[^\"]+)"', block_html)
            link = "https://internshala.com" + link_m.group(1) if link_m else "Unknown Link"
            
            # Company
            company_m = re.search(r'class="company-name"[^>]*>\s*(.*?)\s*</p>', block_html)
            if not company_m:
                company_m = re.search(r'class="company-name"[^>]*>\s*class="company_name_link"[^>]*>(.*?)</a>', block_html, re.DOTALL)
            company = company_m.group(1).strip() if company_m else "Unknown Company"
            company = clean_html(company)
            
            # Location
            loc_match = re.search(r'class="row-1-item locations"[^>]*>(.*?)</div>', block_html, re.DOTALL)
            location = clean_html(loc_match.group(1)) if loc_match else "Unknown"
            
            # Stipend
            stipend_match = re.search(r'class=[\'"]stipend[\'"][^>]*>(.*?)</span>', block_html)
            stipend = stipend_match.group(1).strip() if stipend_match else "N/A"
            
            # Build full text for description and skill checks
            full_text = clean_html(block_html)
            
            # Extract skills from bottom of block (class="tags_container" or tags list)
            # Find words at the end
            skills = ""
            skills_m = re.findall(r'<span class="round_tabs">\s*(.*?)\s*</span>', block_html)
            if skills_m:
                skills = ", ".join([clean_html(s) for s in skills_m])
                
            jobs.append({
                "title": f"[Internshala] {title}",
                "company": company,
                "location": location,
                "budget": stipend,
                "skills": skills,
                "description": full_text,
                "url": link,
                "platform": "Internshala"
            })
            
    return jobs

# ---------------------------------------------------------------------------
# Discord Integration
# ---------------------------------------------------------------------------
def post_to_discord(webhook, job, score, matched):
    """Post single job to Discord as a nice embed."""
    # Build title with Platform
    platform = job.get("platform", "Freelance Platform")
    embed_title = f"{job['title']}"
    
    # Trim to limits
    description = job.get("description", "")
    if len(description) > 600:
        description = description[:600] + "..."
        
    content = {
        "embeds": [
            {
                "title": embed_title[:256],
                "color": 0x2ECC71 if score >= 5 else 0xF1C40F,
                "fields": [
                    {"name": "Company / Poster", "value": job.get("company", "N/A")[:256], "inline": True},
                    {"name": "Budget / Stipend", "value": job.get("budget", "N/A")[:256], "inline": True},
                    {"name": "Location", "value": job.get("location", "N/A")[:256], "inline": True},
                    {"name": "Relevance Score", "value": str(score), "inline": True},
                    {"name": "Skills / Tags", "value": (job.get("skills") if job.get("skills") else "N/A")[:1024], "inline": False},
                    {"name": "Description Preview", "value": description if description else "N/A", "inline": False},
                    {"name": "Link", "value": f"[Apply here]({job['url']})", "inline": False}
                ],
                "footer": {"text": f"Direct fetcher matched keywords: {', '.join(matched[:8]) if matched else 'None'}"}
            }
        ]
    }
    
    data = json.dumps(content).encode("utf-8")
    req = urllib.request.Request(webhook, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "freelance-direct-fetcher/1.0")
    try:
        urllib.request.urlopen(req).read()
        return True
    except urllib.error.HTTPError as e:
        print(f"Discord post failed: {e.code} {e.reason}")
        return False

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def load_cache():
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed": [], "processed_urls": []}

def save_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Direct Freelance Platforms Scraper & Fetcher")
    ap.add_argument("--post", action="store_true", help="Actually post to Discord. Default dry-run.")
    ap.add_argument("--reset-cache", action="store_true", help="Clear cache of processed URLs.")
    args = ap.parse_args()
    
    if args.reset_cache:
        if CACHE_PATH.exists():
            CACHE_PATH.unlink()
            print("Cache cleared.")
            
    strong, soft, exclude, threshold = load_filter()
    webhook = get_env_var("DIRECT_DISCORD_WEBHOOK_URL")
    if not webhook:
        webhook = get_env_var("DISCORD_WEBHOOK_URL")
    
    if args.post and not webhook:
        print("ERROR: --post mode requires DIRECT_DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL in environment or .env file.")
        sys.exit(1)
        
    print(f"[{'POST MODE' if args.post else 'DRY RUN'}] threshold={threshold}")
    
    cache = load_cache()
    processed_urls = set(cache.get("processed_urls", []))
    
    jobs = []
    
    # 1. Fetch Freelancer.com RSS feeds
    freelancer_kws = ["python", "fastapi", "django", "machine-learning", "llm", "ai-agent"]
    for kw in freelancer_kws:
        url = f"https://www.freelancer.com/rss/projects/?keyword={kw}"
        listings = fetch_rss_feed(url)
        for l in listings:
            l["platform"] = "Freelancer.com"
            l["title"] = f"[Freelancer] {l['title']}"
            jobs.append(l)
            
    # 2. Fetch Upwork RSS feed if configured
    upwork_rss = get_env_var("UPWORK_RSS_URL")
    if upwork_rss:
        listings = fetch_rss_feed(upwork_rss)
        for l in listings:
            l["platform"] = "Upwork"
            l["title"] = f"[Upwork] {l['title']}"
            jobs.append(l)
    else:
        print("Upwork RSS feed not configured in environment/env. (Add UPWORK_RSS_URL to .env)")
        
    # 3. Fetch Truelancer RSS feed if configured
    truelancer_rss = get_env_var("TRUELANCER_RSS_URL")
    if truelancer_rss:
        listings = fetch_rss_feed(truelancer_rss)
        for l in listings:
            l["platform"] = "Truelancer"
            l["title"] = f"[Truelancer] {l['title']}"
            jobs.append(l)
            
    # 4. Scrape Internshala
    internshala_kws = ["python", "machine-learning", "fastapi", "django", "react", "nextjs"]
    internshala_jobs = scrape_internshala(internshala_kws)
    jobs.extend(internshala_jobs)
    
    print(f"\nFetched {len(jobs)} total jobs from platforms.")
    
    posted = 0
    skipped_seen = 0
    skipped_low_score = 0
    
    for job in jobs:
        url = job["url"]
        if url in processed_urls:
            skipped_seen += 1
            continue
            
        score, matched = score_project(job, strong, soft, exclude)
        
        if score >= threshold:
            print(f"Match [{score}]: {job['title']} (URL: {url})")
            if args.post:
                success = post_to_discord(webhook, job, score, matched)
                if success:
                    posted += 1
                    processed_urls.add(url)
            else:
                print(f"  Dry-run match. Keywords matched: {matched}")
                posted += 1
        else:
            skipped_low_score += 1
            
    # Save cache
    if args.post:
        cache["processed_urls"] = list(processed_urls)
        save_cache(cache)
        
    print(f"\nDone direct fetch. posted/matched={posted} skipped_seen={skipped_seen} skipped_low_score={skipped_low_score}")

if __name__ == "__main__":
    main()
