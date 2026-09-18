"""
Wayfinder Feature Backend Service & Endpoints
Provides GitHub API integration for tracking wayfinder maps, markdown parsing,
caching with TTL, and FastAPI endpoints.
"""

import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------
GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "parth5012")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
DEFAULT_REPOS = [
    repo.strip()
    for repo in os.environ.get(
        "GITHUB_REPOS",
        "AI-OS,cron-system,orca-marine-intelligence,Vela,artify-bharat-sih,Vendor-Tracker,VelaVoice",
    ).split(",")
    if repo.strip()
]
WAYFINDER_HTML_PATH = Path(__file__).parent / "static" / "wayfinder" / "index.html"
DEFAULT_CACHE_TTL = 300.0  # 5 minutes


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class WayfinderTicket(BaseModel):
    id: Optional[str] = None
    number: Optional[int] = None
    title: str
    url: Optional[str] = None
    state: Optional[str] = None  # "open", "closed"
    is_completed: bool = False
    slug: Optional[str] = None
    raw: Optional[str] = None


class WayfinderMapSummary(BaseModel):
    id: int
    number: int
    title: str
    repo: str
    state: str
    html_url: str
    destination: Optional[str] = None
    notes: Optional[str] = None
    decisions_so_far: List[str] = Field(default_factory=list)
    child_tickets: List[WayfinderTicket] = Field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    labels: List[str] = Field(default_factory=list)


class RateLimitStatus(BaseModel):
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_at: Optional[int] = None


class WayfinderResponse(BaseModel):
    maps: List[WayfinderMapSummary] = Field(default_factory=list)
    total_maps: int = 0
    rate_limit: Optional[RateLimitStatus] = None
    cached: bool = False
    timestamp: str
    error: Optional[str] = None
    authenticated: bool = False


# ---------------------------------------------------------------------------
# Markdown Parsing Utilities
# ---------------------------------------------------------------------------
def parse_wayfinder_body(body: Optional[str]) -> Dict[str, Any]:
    """
    Parses a GitHub issue body labeled `wayfinder:map` and extracts:
    - Destination (under ## Destination or ### Destination)
    - Notes (under ## Notes or ### Notes)
    - Decisions so far (under ## Decisions-so-far or ### Decisions-so-far)
    - Child tickets (bullet points referencing issue numbers or slugs like #123, wayfinder:task)
    """
    if not body:
        return {
            "destination": None,
            "notes": None,
            "decisions_so_far": [],
            "child_tickets": [],
        }

    lines = body.splitlines()
    sections: Dict[str, List[str]] = {}
    current_section: Optional[str] = None

    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    for line in lines:
        h_match = heading_re.match(line)
        if h_match:
            heading_title = h_match.group(2).strip().lower()
            norm_title = re.sub(r"[\s_-]+", " ", heading_title)
            if "destination" in norm_title:
                current_section = "destination"
            elif "note" in norm_title:
                current_section = "notes"
            elif "decision" in norm_title:
                current_section = "decisions"
            else:
                current_section = norm_title
            if current_section not in sections:
                sections[current_section] = []
        elif current_section is not None:
            sections[current_section].append(line)

    destination = (
        "\n".join(sections["destination"]).strip()
        if "destination" in sections and sections["destination"]
        else None
    )
    if destination == "":
        destination = None

    notes = (
        "\n".join(sections["notes"]).strip()
        if "notes" in sections and sections["notes"]
        else None
    )
    if notes == "":
        notes = None

    decisions: List[str] = []
    if "decisions" in sections:
        for d_line in sections["decisions"]:
            d_line_stripped = d_line.strip()
            if not d_line_stripped:
                continue
            # Strip bullet prefixes like -, *, or 1.
            cleaned_d = re.sub(r"^[-*+]\s+", "", d_line_stripped)
            cleaned_d = re.sub(r"^\d+\.\s+", "", cleaned_d).strip()
            if cleaned_d:
                decisions.append(cleaned_d)

    # Extract child tickets from bullet lines across the entire body
    child_tickets: List[WayfinderTicket] = []
    ticket_bullet_re = re.compile(r"^\s*[-*+]\s+(.*)$")
    checkbox_re = re.compile(r"\[([xX\s])\]")
    url_re = re.compile(r"https://github\.com/([\w.-]+/[\w.-]+)/issues/(\d+)")
    slug_issue_re = re.compile(r"([\w.-]+/[\w.-]+)#(\d+)")
    issue_num_re = re.compile(r"#(\d+)")
    slug_tag_re = re.compile(r"\(?(wayfinder:[\w-]+)\)?", re.IGNORECASE)

    for line in lines:
        b_match = ticket_bullet_re.match(line)
        if not b_match:
            continue
        bullet_text = b_match.group(1).strip()

        # Check if this bullet references an issue or task
        has_issue = bool(
            issue_num_re.search(bullet_text)
            or url_re.search(bullet_text)
            or slug_tag_re.search(bullet_text)
            or checkbox_re.search(bullet_text)
        )

        if not has_issue:
            continue

        # Detect checkbox completion
        cb_match = checkbox_re.search(bullet_text)
        is_completed = False
        if cb_match:
            is_completed = cb_match.group(1).strip().lower() == "x"

        # Detect issue number and URL
        issue_number: Optional[int] = None
        issue_url: Optional[str] = None

        url_match = url_re.search(bullet_text)
        if url_match:
            issue_number = int(url_match.group(2))
            issue_url = url_match.group(0)
        else:
            slug_match = slug_issue_re.search(bullet_text)
            if slug_match:
                issue_number = int(slug_match.group(2))
                issue_url = f"https://github.com/{slug_match.group(1)}/issues/{issue_number}"
            else:
                num_match = issue_num_re.search(bullet_text)
                if num_match:
                    issue_number = int(num_match.group(1))

        # Detect slug
        slug_match = slug_tag_re.search(bullet_text)
        slug_val = slug_match.group(1) if slug_match else None

        # Clean title
        clean_title = checkbox_re.sub("", bullet_text)
        if slug_val:
            clean_title = re.sub(re.escape(slug_match.group(0)), "", clean_title)
        clean_title = re.sub(r"\s+", " ", clean_title).strip(" -:")

        # If clean_title is empty or just the issue number, format nicely
        if not clean_title and issue_number:
            clean_title = f"Issue #{issue_number}"

        ticket = WayfinderTicket(
            id=f"#{issue_number}" if issue_number else None,
            number=issue_number,
            title=clean_title,
            url=issue_url,
            state="closed" if is_completed else "open",
            is_completed=is_completed,
            slug=slug_val,
            raw=bullet_text,
        )
        child_tickets.append(ticket)

    return {
        "destination": destination,
        "notes": notes,
        "decisions_so_far": decisions,
        "child_tickets": child_tickets,
    }


def extract_repo_name(item: Dict[str, Any]) -> str:
    """Extract owner/repo string from GitHub API issue object."""
    if "repository_url" in item and item["repository_url"]:
        parts = item["repository_url"].rstrip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
    if "html_url" in item and item["html_url"]:
        match = re.search(r"github\.com/([^/]+/[^/]+)/issues", item["html_url"])
        if match:
            return match.group(1)
    return "parth5012/unknown"


# ---------------------------------------------------------------------------
# Wayfinder Service with In-Memory Caching
# ---------------------------------------------------------------------------
class WayfinderService:
    def __init__(self, cache_ttl: float = DEFAULT_CACHE_TTL):
        self.cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._cached_response: Optional[WayfinderResponse] = None
        self._cached_time: float = 0.0

    def _get_token(self) -> Optional[str]:
        # Read live so Vercel/Render env changes apply without import reload.
        # Strips accidental quotes/whitespace from dashboard copy-paste.
        raw = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or GITHUB_TOKEN
        if not raw:
            return None
        token = raw.strip().strip('"').strip("'")
        return token or None

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "cron-system-wayfinder",
        }
        if self._get_token():
            headers["Authorization"] = f"Bearer {self._get_token()}"
        return headers

    def _extract_rate_limit(self, response_headers: Any) -> RateLimitStatus:
        def parse_header_int(key: str) -> Optional[int]:
            val = response_headers.get(key)
            if val is not None and str(val).isdigit():
                return int(val)
            return None

        return RateLimitStatus(
            limit=parse_header_int("x-ratelimit-limit"),
            remaining=parse_header_int("x-ratelimit-remaining"),
            reset_at=parse_header_int("x-ratelimit-reset"),
        )

    async def _fetch_from_github(self) -> WayfinderResponse:
        owner = GITHUB_OWNER
        headers = self._get_headers()
        timeout = httpx.Timeout(15.0)

        issues: List[Dict[str, Any]] = []
        rate_limit_status: Optional[RateLimitStatus] = None
        error_msg: Optional[str] = None

        search_base = "https://api.github.com/search/issues"
        search_query = f"label:wayfinder:map user:{owner}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            search_response = None
            try:
                # Paginate search (per_page=100, up to 5 pages) — first page
                # alone misses repos when total >30 due to ranking.
                search_ok = False
                for page in range(1, 6):
                    search_response = await client.get(
                        search_base,
                        headers=headers,
                        params={
                            "q": search_query,
                            "per_page": 100,
                            "page": page,
                        },
                    )
                    rate_limit_status = self._extract_rate_limit(
                        search_response.headers
                    )

                    if search_response.status_code == 200:
                        data = search_response.json()
                        page_items = data.get("items", [])
                        issues.extend(page_items)
                        search_ok = True
                        # Last page when fewer than full page returned
                        if len(page_items) < 100:
                            break
                    elif search_response.status_code in (403, 429):
                        error_msg = "GitHub Search API rate limited. Attempting repository fallback."
                        break
                    else:
                        error_msg = f"GitHub Search API returned status {search_response.status_code}: {search_response.text}"
                        break

                # Union with direct repo queries to guarantee DEFAULT_REPOS
                # coverage (search ranking can omit repos on page 1).
                try:
                    repo_issues = await self._fallback_repo_query(client, headers)
                    if repo_issues:
                        if not issues:
                            issues = repo_issues
                        else:
                            issues = issues + repo_issues
                        if search_ok:
                            error_msg = None
                except Exception as inner_e:
                    if not issues:
                        error_msg = f"Failed GitHub API search and fallback: {str(inner_e)}"
            except Exception as e:
                error_msg = f"Failed to connect to GitHub API: {str(e)}"
                # Attempt fallback
                try:
                    repo_issues = await self._fallback_repo_query(client, headers)
                    if repo_issues:
                        issues = repo_issues
                        error_msg = None
                except Exception as inner_e:
                    error_msg = f"Failed GitHub API search and fallback: {str(e)} | {str(inner_e)}"

        # Deduplicate issues by ID
        unique_issues: Dict[int, Dict[str, Any]] = {}
        for item in issues:
            item_id = item.get("id")
            if item_id and item_id not in unique_issues:
                unique_issues[item_id] = item

        # Build Map Summaries
        summaries: List[WayfinderMapSummary] = []
        for item in unique_issues.values():
            body = item.get("body") or ""
            parsed = parse_wayfinder_body(body)

            labels = [
                label["name"] if isinstance(label, dict) else str(label)
                for label in item.get("labels", [])
            ]

            summary = WayfinderMapSummary(
                id=item["id"],
                number=item["number"],
                title=item["title"],
                repo=extract_repo_name(item),
                state=item.get("state", "open"),
                html_url=item.get("html_url", ""),
                destination=parsed["destination"],
                notes=parsed["notes"],
                decisions_so_far=parsed["decisions_so_far"],
                child_tickets=parsed["child_tickets"],
                created_at=item.get("created_at"),
                updated_at=item.get("updated_at"),
                labels=labels,
            )
            summaries.append(summary)

        # Sort: open first, then recently updated
        summaries.sort(
            key=lambda m: (m.state != "open", m.updated_at or ""), reverse=False
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        return WayfinderResponse(
            maps=summaries,
            total_maps=len(summaries),
            rate_limit=rate_limit_status,
            cached=False,
            timestamp=now_iso,
            error=error_msg,
            authenticated=bool(self._get_token()),
        )

    async def _fallback_repo_query(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> List[Dict[str, Any]]:
        """Direct per-repo queries — also unions with search for full coverage."""
        all_items: List[Dict[str, Any]] = []
        live_repos = [
            r.strip()
            for r in os.environ.get(
                "GITHUB_REPOS",
                "AI-OS,cron-system,orca-marine-intelligence,Vela,artify-bharat-sih,Vendor-Tracker,VelaVoice",
            ).split(",")
            if r.strip()
        ]
        repos_to_query = live_repos if live_repos else DEFAULT_REPOS
        for repo_name in repos_to_query:
            repo_slug = (
                repo_name
                if "/" in repo_name
                else f"{GITHUB_OWNER}/{repo_name}"
            )
            repo_url = f"https://api.github.com/repos/{repo_slug}/issues?labels=wayfinder:map&state=all"
            try:
                resp = await client.get(repo_url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        all_items.extend(data)
            except Exception:
                continue
        return all_items

    async def get_maps(self, refresh: bool = False) -> WayfinderResponse:
        current_time = time.time()
        with self._lock:
            if (
                not refresh
                and self._cached_response is not None
                and (current_time - self._cached_time) < self.cache_ttl
            ):
                cached_copy = self._cached_response.model_copy()
                cached_copy.cached = True
                return cached_copy

        response = await self._fetch_from_github()

        with self._lock:
            self._cached_response = response
            self._cached_time = time.time()

        return response


# Global singleton instance
_wayfinder_service = WayfinderService()


def get_wayfinder_service() -> WayfinderService:
    return _wayfinder_service


# ---------------------------------------------------------------------------
# Clean HTML Fallback Template
# ---------------------------------------------------------------------------
FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Wayfinder - Strategic Project Maps</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-border: #334155;
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --accent: #38bdf8;
      --accent-hover: #0ea5e9;
      --success: #34d399;
      --closed: #64748b;
      --pill-bg: #334155;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      padding: 24px;
      line-height: 1.5;
    }
    .container {
      max-width: 1080px;
      margin: 0 auto;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--card-border);
    }
    .title-group h1 {
      font-size: 1.75rem;
      font-weight: 700;
      color: var(--text-main);
    }
    .title-group p {
      font-size: 0.9rem;
      color: var(--text-muted);
      margin-top: 4px;
    }
    .actions {
      display: flex;
      gap: 12px;
      align-items: center;
    }
    button.btn-refresh {
      background-color: var(--accent);
      color: #0f172a;
      border: none;
      padding: 8px 16px;
      font-weight: 600;
      border-radius: 6px;
      cursor: pointer;
      font-size: 0.875rem;
      transition: background-color 0.15s ease;
    }
    button.btn-refresh:hover {
      background-color: var(--accent-hover);
    }
    .meta-bar {
      display: flex;
      gap: 16px;
      font-size: 0.8rem;
      color: var(--text-muted);
      margin-bottom: 20px;
      flex-wrap: wrap;
    }
    .meta-item {
      background: var(--card-bg);
      padding: 6px 12px;
      border-radius: 6px;
      border: 1px solid var(--card-border);
    }
    .map-grid {
      display: grid;
      grid-template-columns: 1fr;
      gap: 20px;
    }
    .map-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 8px;
      padding: 20px;
      box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.2);
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 12px;
      gap: 12px;
    }
    .card-title {
      font-size: 1.25rem;
      font-weight: 600;
      color: var(--text-main);
      text-decoration: none;
    }
    .card-title:hover {
      color: var(--accent);
      text-decoration: underline;
    }
    .badges {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }
    .badge {
      font-size: 0.75rem;
      padding: 3px 8px;
      border-radius: 9999px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .badge-open {
      background-color: rgba(52, 211, 153, 0.15);
      color: var(--success);
      border: 1px solid var(--success);
    }
    .badge-closed {
      background-color: rgba(100, 116, 139, 0.2);
      color: var(--closed);
      border: 1px solid var(--closed);
    }
    .badge-repo {
      background-color: var(--pill-bg);
      color: var(--text-muted);
      border: 1px solid var(--card-border);
    }
    .section-block {
      margin-top: 14px;
      padding-top: 14px;
      border-top: 1px solid var(--card-border);
    }
    .section-label {
      font-size: 0.75rem;
      font-weight: 700;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 6px;
    }
    .destination-box {
      background: rgba(56, 189, 248, 0.08);
      border-left: 3px solid var(--accent);
      padding: 10px 14px;
      border-radius: 0 6px 6px 0;
      font-size: 0.95rem;
      color: #e2e8f0;
      white-space: pre-wrap;
    }
    .decisions-list, .tickets-list {
      list-style: none;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }
    .decisions-list li {
      font-size: 0.9rem;
      color: #cbd5e1;
      padding-left: 14px;
      position: relative;
    }
    .decisions-list li::before {
      content: "•";
      color: var(--accent);
      position: absolute;
      left: 0;
    }
    .ticket-item {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 0.9rem;
      padding: 6px 10px;
      background: rgba(15, 23, 42, 0.5);
      border: 1px solid var(--card-border);
      border-radius: 6px;
    }
    .ticket-checkbox {
      accent-color: var(--success);
      width: 16px;
      height: 16px;
    }
    .ticket-title {
      flex: 1;
      color: #e2e8f0;
    }
    .ticket-title.completed {
      text-decoration: line-through;
      color: var(--text-muted);
    }
    .ticket-num {
      font-family: monospace;
      font-size: 0.8rem;
      color: var(--accent);
      text-decoration: none;
    }
    .ticket-num:hover {
      text-decoration: underline;
    }
    .ticket-slug {
      font-size: 0.75rem;
      background: var(--pill-bg);
      color: var(--text-muted);
      padding: 2px 6px;
      border-radius: 4px;
    }
    .notes-box {
      font-size: 0.85rem;
      color: var(--text-muted);
      white-space: pre-wrap;
    }
    .empty-state {
      text-align: center;
      padding: 60px 20px;
      color: var(--text-muted);
      background: var(--card-bg);
      border-radius: 8px;
      border: 1px dashed var(--card-border);
    }
    .error-banner {
      background-color: rgba(239, 68, 68, 0.15);
      border: 1px solid #ef4444;
      color: #fca5a5;
      padding: 12px 16px;
      border-radius: 6px;
      margin-bottom: 20px;
      font-size: 0.9rem;
      display: none;
    }
    #loading {
      text-align: center;
      padding: 40px;
      color: var(--text-muted);
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="title-group">
        <h1>🧭 Wayfinder Maps</h1>
        <p>Strategic decision tracking & execution maps across repositories</p>
      </div>
      <div class="actions">
        <button class="btn-refresh" id="refreshBtn" onclick="loadMaps(true)">Refresh</button>
      </div>
    </header>

    <div class="error-banner" id="errorBanner"></div>

    <div class="meta-bar" id="metaBar" style="display:none;">
      <div class="meta-item">Total Maps: <strong id="metaTotal">0</strong></div>
      <div class="meta-item">Cached: <strong id="metaCached">No</strong></div>
      <div class="meta-item">Rate Limit: <strong id="metaRateLimit">-</strong></div>
      <div class="meta-item">Last Updated: <span id="metaTime">-</span></div>
    </div>

    <div id="loading">Loading Wayfinder maps...</div>
    <div class="map-grid" id="mapGrid"></div>
  </div>

  <script>
    async function loadMaps(refresh = false) {
      const loading = document.getElementById('loading');
      const grid = document.getElementById('mapGrid');
      const errorBanner = document.getElementById('errorBanner');
      const metaBar = document.getElementById('metaBar');

      loading.style.display = 'block';
      errorBanner.style.display = 'none';

      try {
        const url = '/api/wayfinder' + (refresh ? '?refresh=true' : '');
        const res = await fetch(url);
        if (!res.ok) {
          throw new Error('Failed to load: ' + res.status + ' ' + res.statusText);
        }
        const data = await res.json();

        loading.style.display = 'none';
        metaBar.style.display = 'flex';

        document.getElementById('metaTotal').textContent = data.total_maps;
        document.getElementById('metaCached').textContent = data.cached ? 'Yes (TTL 300s)' : 'No (Live API)';
        if (data.rate_limit && data.rate_limit.remaining !== null) {
          document.getElementById('metaRateLimit').textContent = `${data.rate_limit.remaining} / ${data.rate_limit.limit}`;
        } else {
          document.getElementById('metaRateLimit').textContent = 'N/A';
        }
        document.getElementById('metaTime').textContent = new Date(data.timestamp).toLocaleTimeString();

        if (data.error) {
          errorBanner.textContent = data.error;
          errorBanner.style.display = 'block';
        }

        renderMaps(data.maps);
      } catch (err) {
        loading.style.display = 'none';
        errorBanner.textContent = err.message;
        errorBanner.style.display = 'block';
      }
    }

    function renderMaps(maps) {
      const grid = document.getElementById('mapGrid');
      grid.innerHTML = '';

      if (!maps || maps.length === 0) {
        grid.innerHTML = '<div class="empty-state"><h3>No Wayfinder Maps Found</h3><p style="margin-top:8px;">Issues labeled <code>wayfinder:map</code> will appear here automatically.</p></div>';
        return;
      }

      maps.forEach(map => {
        const card = document.createElement('div');
        card.className = 'map-card';

        const stateBadgeClass = map.state === 'open' ? 'badge-open' : 'badge-closed';

        let destinationHtml = '';
        if (map.destination) {
          destinationHtml = `
            <div class="section-block">
              <div class="section-label">Destination</div>
              <div class="destination-box">${escapeHtml(map.destination)}</div>
            </div>`;
        }

        let decisionsHtml = '';
        if (map.decisions_so_far && map.decisions_so_far.length > 0) {
          const items = map.decisions_so_far.map(d => `<li>${escapeHtml(d)}</li>`).join('');
          decisionsHtml = `
            <div class="section-block">
              <div class="section-label">Decisions So Far</div>
              <ul class="decisions-list">${items}</ul>
            </div>`;
        }

        let ticketsHtml = '';
        if (map.child_tickets && map.child_tickets.length > 0) {
          const ticketItems = map.child_tickets.map(t => {
            const completedClass = t.is_completed ? 'completed' : '';
            const checkedAttr = t.is_completed ? 'checked' : '';
            const numHtml = t.number ? (t.url ? `<a class="ticket-num" href="${t.url}" target="_blank">#${t.number}</a>` : `<span class="ticket-num">#${t.number}</span>`) : '';
            const slugHtml = t.slug ? `<span class="ticket-slug">${escapeHtml(t.slug)}</span>` : '';
            return `
              <div class="ticket-item">
                <input type="checkbox" class="ticket-checkbox" disabled ${checkedAttr}>
                ${numHtml}
                <span class="ticket-title ${completedClass}">${escapeHtml(t.title)}</span>
                ${slugHtml}
              </div>`;
          }).join('');

          ticketsHtml = `
            <div class="section-block">
              <div class="section-label">Child Tickets / Tasks</div>
              <div class="tickets-list">${ticketItems}</div>
            </div>`;
        }

        let notesHtml = '';
        if (map.notes) {
          notesHtml = `
            <div class="section-block">
              <div class="section-label">Notes</div>
              <div class="notes-box">${escapeHtml(map.notes)}</div>
            </div>`;
        }

        card.innerHTML = `
          <div class="card-header">
            <div>
              <a href="${map.html_url}" target="_blank" class="card-title">#${map.number} ${escapeHtml(map.title)}</a>
            </div>
            <div class="badges">
              <span class="badge badge-repo">${escapeHtml(map.repo)}</span>
              <span class="badge ${stateBadgeClass}">${map.state}</span>
            </div>
          </div>
          ${destinationHtml}
          ${decisionsHtml}
          ${ticketsHtml}
          ${notesHtml}
        `;

        grid.appendChild(card);
      });
    }

    function escapeHtml(str) {
      if (!str) return '';
      return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }

    // Initial load on page open
    loadMaps(false);
  </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# FastAPI APIRouter Definition
# ---------------------------------------------------------------------------
router = APIRouter(tags=["wayfinder"])


@router.get("/api/wayfinder", response_model=WayfinderResponse)
async def get_wayfinder_data(
    refresh: bool = Query(
        False, description="Bypass in-memory cache and query GitHub API directly"
    )
):
    """
    Returns aggregated Wayfinder maps from GitHub issues labeled `wayfinder:map`.
    Includes parsed destinations, decisions so far, notes, child tickets, and rate limits.
    """
    service = get_wayfinder_service()
    return await service.get_maps(refresh=refresh)


@router.get("/wayfinder", response_class=HTMLResponse)
async def get_wayfinder_ui():
    """
    Returns the Wayfinder visual UI dashboard.
    Renders static/wayfinder/index.html if present on disk, otherwise serves the clean HTML fallback.
    """
    if WAYFINDER_HTML_PATH.exists() and WAYFINDER_HTML_PATH.is_file():
        content = WAYFINDER_HTML_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=content, status_code=200)
    return HTMLResponse(content=FALLBACK_HTML, status_code=200)
