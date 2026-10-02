"""
GitHub Pull Requests Module
Aggregates every open pull request across the configured GitHub repositories
(authored by, reviewing for, or assigned to the owner) and exposes both a JSON
API and a standalone mobile-first HTML view.

Mirrors the architecture of ``wayfinder.py``: env-driven config, pydantic
models, an in-memory TTL cache, a GitHub Search API path with a per-repo
fallback, and an ``APIRouter`` mounted from ``main.py``.
"""

import asyncio
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
        "AI-OS,cron-system,orca-marine-intelligence,Vela,artify-bharat-sih,"
        "Vendor-Tracker,VelaVoice,flyrank-capstone-metering-billing",
    ).split(",")
    if repo.strip()
]
PULL_REQUESTS_HTML_PATH = (
    Path(__file__).parent / "static" / "pull-requests" / "index.html"
)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_CACHE_TTL = 120.0  # 2 minutes — PR state changes faster than wayfinder maps
SEARCH_MAX_PAGES = 3
# Diff stats (additions/deletions) only exist on the single-PR endpoint, which
# costs one request per PR. Cap the enrichment so an unauthenticated 60 req/hr
# budget can never be drained by a page refresh.
PR_DETAIL_LIMIT = 20
PR_DETAIL_LIMIT_UNAUTH = 8
PR_DETAIL_CONCURRENCY = 6


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class PullRequest(BaseModel):
    id: int
    number: int
    title: str
    repo: str
    author: Optional[str] = None
    html_url: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    draft: bool = False
    labels: List[str] = Field(default_factory=list)
    comments_count: int = 0
    additions: int = 0
    deletions: int = 0
    branch_head: Optional[str] = None
    branch_base: Optional[str] = None
    # Why this PR is in the list: "author", "reviewer" or "assignee".
    role: str = "author"
    review_requested: bool = False


class RateLimitStatus(BaseModel):
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset_at: Optional[int] = None


class PullRequestsResponse(BaseModel):
    prs: List[PullRequest] = Field(default_factory=list)
    total_count: int = 0
    cached: bool = False
    rate_limit_remaining: int = 0
    rate_limit: Optional[RateLimitStatus] = None
    repos: List[str] = Field(default_factory=list)
    authenticated: bool = False
    timestamp: str
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Query & Parsing Utilities
# ---------------------------------------------------------------------------
def build_search_queries(involved: bool) -> List[str]:
    """
    Base query is always "authored by owner". When `involved` is set, PRs where
    the owner is a requested reviewer or the assignee are unioned in.
    """
    queries = [f"type:pr state:open author:{GITHUB_OWNER}"]
    if involved:
        queries.append(f"type:pr state:open review-requested:{GITHUB_OWNER}")
        queries.append(f"type:pr state:open assignee:{GITHUB_OWNER}")
    return queries


def role_for_query(query: str) -> str:
    if "author:" in query:
        return "author"
    if "review-requested:" in query:
        return "reviewer"
    return "assignee"


# Lower wins when the same PR is matched by several queries.
_ROLE_PRIORITY = {"author": 0, "reviewer": 1, "assignee": 2}


def extract_repo_slug(item: Dict[str, Any]) -> str:
    """Extract owner/repo from a search item or a repo pulls listing item."""
    repository_url = item.get("repository_url")
    if repository_url:
        parts = str(repository_url).rstrip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"

    html_url = item.get("html_url") or ""
    if html_url:
        # https://github.com/owner/repo/pull/7
        match = re.search(r"github\.com/([^/]+/[^/]+)/pulls?/", str(html_url))
        if match:
            return match.group(1)

    return f"{GITHUB_OWNER}/unknown"


def _ref_name(branch: Any) -> Optional[str]:
    if isinstance(branch, dict):
        ref = branch.get("ref")
        return str(ref) if ref else None
    if isinstance(branch, str) and branch:
        return branch
    return None


def parse_pull_request_item(
    item: Dict[str, Any],
    role: str = "author",
    review_requested: bool = False,
) -> Optional[PullRequest]:
    """
    Normalize a GitHub search item or repo pulls item into a PullRequest.
    Returns None for anything that is not a pull request.
    """
    if "pull_request" not in item and "merged_at" not in item and "head" not in item:
        # Plain issues share the search endpoint; skip them.
        return None

    user = item.get("user") or {}
    author = user.get("login") if isinstance(user, dict) else None
    labels = [
        label["name"] if isinstance(label, dict) else str(label)
        for label in (item.get("labels") or [])
    ]

    return PullRequest(
        id=int(item.get("id") or 0),
        number=int(item.get("number") or 0),
        title=str(item.get("title") or "(untitled pull request)"),
        repo=extract_repo_slug(item),
        author=author,
        html_url=str(item.get("html_url") or ""),
        created_at=item.get("created_at"),
        updated_at=item.get("updated_at"),
        draft=bool(item.get("draft") or False),
        labels=labels,
        comments_count=int(item.get("comments") or 0),
        additions=int(item.get("additions") or 0),
        deletions=int(item.get("deletions") or 0),
        branch_head=_ref_name(item.get("head")),
        branch_base=_ref_name(item.get("base")),
        role=role,
        review_requested=review_requested,
    )


def pull_request_key(item: Dict[str, Any]) -> Tuple[str, int]:
    """
    Stable identity of a pull request.

    Deliberately *not* the item id: GitHub's Search API reports the **issue**
    id for a PR while `GET /repos/{owner}/{repo}/pulls` reports the **pull
    request** id, so the same PR arrives twice with different ids whenever both
    sources are unioned. (owner/repo, number) is the only reliable key.
    """
    return (extract_repo_slug(item), int(item.get("number") or 0))


def merge_pull_request(target: PullRequest, other: PullRequest) -> PullRequest:
    """
    Fold `other` into `target`, keeping the richer value for each field.
    Search items carry labels/comments/draft; pulls listings carry branches.
    """
    if not target.author and other.author:
        target.author = other.author
    if not target.branch_head and other.branch_head:
        target.branch_head = other.branch_head
    if not target.branch_base and other.branch_base:
        target.branch_base = other.branch_base
    if not target.additions and other.additions:
        target.additions = other.additions
    if not target.deletions and other.deletions:
        target.deletions = other.deletions
    if not target.labels and other.labels:
        target.labels = other.labels
    if not target.created_at and other.created_at:
        target.created_at = other.created_at
    if not target.html_url and other.html_url:
        target.html_url = other.html_url
    if other.review_requested:
        target.review_requested = True
    if _ROLE_PRIORITY.get(other.role, 99) < _ROLE_PRIORITY.get(target.role, 99):
        target.role = other.role
    return target


def _merge_rate_limit(
    current: Optional[RateLimitStatus], incoming: Optional[RateLimitStatus]
) -> Optional[RateLimitStatus]:
    """
    Keep the most recent reading, but never paper over an exhausted budget:
    once any response reports 0 remaining, stay at 0 until the next real fetch.
    """
    if incoming is None:
        return current
    if current is not None and current.remaining == 0:
        return current
    if current is not None and current.remaining is not None and incoming.remaining is None:
        return current
    return incoming


# ---------------------------------------------------------------------------
# PullRequest Service with In-Memory Caching
# ---------------------------------------------------------------------------
class PullRequestService:
    def __init__(self, cache_ttl: float = DEFAULT_CACHE_TTL):
        self.cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._cache: Dict[bool, Tuple[PullRequestsResponse, float]] = {}

    def _get_token(self) -> Optional[str]:
        # Read live so Render/Vercel env changes apply without an import reload.
        raw = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or GITHUB_TOKEN
        if not raw:
            return None
        token = raw.strip().strip('"').strip("'")
        return token or None

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "cron-system-pull-requests",
        }
        token = self._get_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get_repos(self) -> List[str]:
        live = [
            repo.strip()
            for repo in os.environ.get("GITHUB_REPOS", "").split(",")
            if repo.strip()
        ]
        repos = live or DEFAULT_REPOS
        return [
            repo if "/" in repo else f"{GITHUB_OWNER}/{repo}" for repo in repos
        ]

    def _extract_rate_limit(self, response_headers: Any) -> Optional[RateLimitStatus]:
        def parse_header_int(key: str) -> Optional[int]:
            value = None
            try:
                value = response_headers.get(key)
            except AttributeError:
                return None
            if value is not None and str(value).isdigit():
                return int(value)
            return None

        if response_headers is None:
            return None
        return RateLimitStatus(
            limit=parse_header_int("x-ratelimit-limit"),
            remaining=parse_header_int("x-ratelimit-remaining"),
            reset_at=parse_header_int("x-ratelimit-reset"),
        )

    # -- GitHub data sources ------------------------------------------------
    async def _search_issues(
        self, client: httpx.AsyncClient, headers: Dict[str, str], query: str
    ) -> Tuple[List[Dict[str, Any]], Optional[RateLimitStatus], Optional[str]]:
        """Paginated Search API lookup. Returns (items, rate_limit, error)."""
        items: List[Dict[str, Any]] = []
        rate_limit: Optional[RateLimitStatus] = None

        for page in range(1, SEARCH_MAX_PAGES + 1):
            response = await client.get(
                f"{GITHUB_API_BASE}/search/issues",
                headers=headers,
                params={"q": query, "per_page": 100, "page": page},
            )
            rate_limit = _merge_rate_limit(
                rate_limit, self._extract_rate_limit(response.headers)
            )

            if response.status_code == 200:
                data = response.json() or {}
                page_items = data.get("items") or []
                items.extend(page_items)
                if len(page_items) < 100:
                    break
            elif response.status_code in (403, 429):
                return (
                    items,
                    rate_limit,
                    "GitHub Search API rate limited. Attempting repository fallback.",
                )
            else:
                detail = (response.text or "")[:200]
                return (
                    items,
                    rate_limit,
                    f"GitHub Search API returned status {response.status_code}: {detail}",
                )

        return items, rate_limit, None

    async def _fetch_repo_pulls(
        self, client: httpx.AsyncClient, headers: Dict[str, str]
    ) -> Tuple[List[Dict[str, Any]], Optional[RateLimitStatus]]:
        """
        Direct per-repo pulls listing. Unions with search for full coverage and
        doubles as the fallback when Search API is rate limited or unreachable.
        """
        all_items: List[Dict[str, Any]] = []
        rate_limit: Optional[RateLimitStatus] = None

        for repo_slug in self._get_repos():
            try:
                response = await client.get(
                    f"{GITHUB_API_BASE}/repos/{repo_slug}/pulls",
                    headers=headers,
                    params={"state": "open", "per_page": 100},
                )
            except Exception:
                continue
            rate_limit = _merge_rate_limit(
                rate_limit, self._extract_rate_limit(response.headers)
            )
            if response.status_code == 200:
                data = response.json() or []
                if isinstance(data, list):
                    all_items.extend(data)

        return all_items, rate_limit

    async def _enrich_diff_stats(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        prs: List[PullRequest],
    ) -> None:
        """
        Fill in additions/deletions (only available on the single-PR endpoint)
        and any missing branch names, for a bounded number of PRs.
        """
        limit = PR_DETAIL_LIMIT if self._get_token() else PR_DETAIL_LIMIT_UNAUTH
        candidates = [pr for pr in prs if pr.additions == 0 and pr.deletions == 0]
        candidates = candidates[:limit]
        if not candidates:
            return

        semaphore = asyncio.Semaphore(PR_DETAIL_CONCURRENCY)

        async def fetch_one(pr: PullRequest) -> None:
            async with semaphore:
                try:
                    response = await client.get(
                        f"{GITHUB_API_BASE}/repos/{pr.repo}/pulls/{pr.number}",
                        headers=headers,
                    )
                except Exception:
                    return
                if response.status_code != 200:
                    return
                data = response.json() or {}
                pr.additions = int(data.get("additions") or 0)
                pr.deletions = int(data.get("deletions") or 0)
                if "draft" in data:
                    pr.draft = bool(data.get("draft") or False)
                head_ref = _ref_name(data.get("head"))
                base_ref = _ref_name(data.get("base"))
                if head_ref:
                    pr.branch_head = head_ref
                if base_ref:
                    pr.branch_base = base_ref

        await asyncio.gather(*(fetch_one(pr) for pr in candidates))

    async def _fetch_from_github(self, involved: bool) -> PullRequestsResponse:
        headers = self._get_headers()
        timeout = httpx.Timeout(15.0)

        raw_items: List[Dict[str, Any]] = []
        # Keyed by (owner/repo, number) — never by item id, see
        # pull_request_key() for why the two GitHub id spaces collide.
        roles: Dict[Tuple[str, int], str] = {}
        review_flagged: Dict[Tuple[str, int], bool] = {}
        rate_limit: Optional[RateLimitStatus] = None
        error_msg: Optional[str] = None
        search_ok = False

        async with httpx.AsyncClient(timeout=timeout) as client:
            for query in build_search_queries(involved):
                query_role = role_for_query(query)
                try:
                    items, query_rate_limit, query_error = await self._search_issues(
                        client, headers, query
                    )
                except Exception as exc:
                    error_msg = f"Failed to connect to GitHub API: {exc}"
                    break

                rate_limit = _merge_rate_limit(rate_limit, query_rate_limit)
                if query_error:
                    error_msg = query_error
                    break

                search_ok = True
                for item in items:
                    if not item.get("id"):
                        continue
                    raw_items.append(item)
                    key = pull_request_key(item)
                    # Role priority: authored PRs badge as "author", then
                    # "reviewer", then "assignee".
                    if _ROLE_PRIORITY[query_role] < _ROLE_PRIORITY.get(
                        roles.get(key, "assignee"), 99
                    ):
                        roles[key] = query_role
                    if query_role == "reviewer":
                        review_flagged[key] = True

            # Union with direct repo listings: search ranking can omit repos and
            # the listing is the recovery path when Search is rate limited.
            repo_items: List[Dict[str, Any]] = []
            repo_rate_limit: Optional[RateLimitStatus] = None
            try:
                repo_items, repo_rate_limit = await self._fetch_repo_pulls(
                    client, headers
                )
            except Exception as exc:
                if not search_ok:
                    error_msg = f"Failed GitHub API search and fallback: {exc}"

            rate_limit = _merge_rate_limit(rate_limit, repo_rate_limit)
            if repo_items:
                raw_items.extend(repo_items)
                if search_ok:
                    error_msg = None

            prs: List[PullRequest] = []
            seen: Dict[Tuple[str, int], PullRequest] = {}
            for item in raw_items:
                parsed = parse_pull_request_item(
                    item,
                    role=roles.get(pull_request_key(item), "author"),
                    review_requested=review_flagged.get(pull_request_key(item), False),
                )
                if parsed is None:
                    continue
                key = pull_request_key(item)
                existing = seen.get(key)
                if existing is not None:
                    merge_pull_request(existing, parsed)
                    continue
                seen[key] = parsed
                prs.append(parsed)

            # Most recently updated first — the PRs most likely to need action.
            prs.sort(key=lambda pr: pr.updated_at or "", reverse=True)

            await self._enrich_diff_stats(client, headers, prs)

        now_iso = datetime.now(timezone.utc).isoformat()
        return PullRequestsResponse(
            prs=prs,
            total_count=len(prs),
            cached=False,
            rate_limit_remaining=(rate_limit.remaining if rate_limit else None) or 0,
            rate_limit=rate_limit,
            repos=self._get_repos(),
            authenticated=bool(self._get_token()),
            timestamp=now_iso,
            error=error_msg,
        )

    async def get_pull_requests(
        self, refresh: bool = False, involved: bool = True
    ) -> PullRequestsResponse:
        key = bool(involved)
        current_time = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if (
                not refresh
                and entry is not None
                and (current_time - entry[1]) < self.cache_ttl
            ):
                cached_copy = entry[0].model_copy()
                cached_copy.cached = True
                return cached_copy

        response = await self._fetch_from_github(key)

        with self._lock:
            self._cache[key] = (response, time.time())

        return response


# Global singleton instance
_pull_request_service = PullRequestService()


def get_pull_request_service() -> PullRequestService:
    return _pull_request_service


# ---------------------------------------------------------------------------
# Clean HTML Fallback Template
# ---------------------------------------------------------------------------
FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Pull Requests | Cron System</title>
  <style>
    :root { --bg:#f8f9fa; --card:#fff; --text:#18181b; --muted:#71717a; --border:#e4e4e7; --primary:#2563eb; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
           background: var(--bg); color: var(--text); min-height: 100vh; padding-bottom: 96px; }
    .wrap { max-width: 900px; margin: 0 auto; padding: 18px 16px; }
    .top { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap;
           border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
    h1 { font-size: 1.3rem; font-weight: 700; }
    .sub { font-size: .82rem; color: var(--muted); }
    .pill { font-size: .74rem; padding: 6px 12px; border: 1px solid var(--border); border-radius: 99px;
            background: var(--card); color: var(--muted); }
    .sk { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
          padding: 14px; margin-bottom: 10px; }
    .sk i { display: block; height: 12px; border-radius: 6px; margin-bottom: 8px;
            background: linear-gradient(90deg, var(--border), #f4f4f5, var(--border));
            background-size: 200% 100%; animation: sh 1.2s linear infinite; }
    .sk i.w60 { width: 60%; } .sk i.w40 { width: 40%; } .sk i.w25 { width: 25%; }
    @keyframes sh { to { background-position: -200% 0; } }
    .pr { background: var(--card); border: 1px solid var(--border); border-radius: 12px;
          padding: 14px; margin-bottom: 10px; display: block; text-decoration: none; color: inherit; }
    .meta { font-size: .76rem; color: var(--muted); margin-top: 4px; }
    .b { font-size: .7rem; font-weight: 700; padding: 2px 8px; border-radius: 99px; }
    .b-open { background: rgba(16,185,129,.15); color: #059669; }
    .b-draft { background: rgba(113,113,122,.18); color: var(--muted); }
    .empty { text-align: center; color: var(--muted); padding: 48px 20px; border: 1px dashed var(--border);
             border-radius: 12px; background: var(--card); }
    .bnav { position: fixed; left: 0; right: 0; bottom: 0; display: flex; background: var(--card);
            border-top: 1px solid var(--border); z-index: 50;
            padding-bottom: env(safe-area-inset-bottom, 16px); }
    .bnav a { flex: 1; text-align: center; text-decoration: none; color: var(--muted);
              font-size: .7rem; font-weight: 600; padding: 12px 0; min-height: 48px; }
    .bnav a.on { color: var(--primary); }
    .bnav span { display: block; font-size: 1.15rem; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div>
        <h1>&#128200; Pull Requests</h1>
        <div class="sub">Open PRs across your GitHub repositories</div>
      </div>
      <span class="pill" id="pill">Loading...</span>
    </div>
    <div id="list"></div>
  </div>
  <nav class="bnav">
    <a href="/wayfinder"><span>&#128506;</span>Wayfinder</a>
    <a href="/pull-requests" class="on"><span>&#128256;</span>PRs</a>
    <a href="/pwa/"><span>&#128193;</span>Content</a>
    <a href="/pwa/"><span>&#9201;</span>Jobs</a>
  </nav>
  <script>
    function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
    function render(prs){
      var list=document.getElementById('list');
      if(!prs.length){list.innerHTML='<div class="empty"><b>No open pull requests found.</b><p>Check back after the next push.</p></div>';return}
      list.innerHTML=prs.map(function(p){
        return '<a class="pr" href="'+esc(p.html_url)+'" target="_blank" rel="noopener">'
          +'<b>#'+p.number+' '+esc(p.title)+'</b>'
          +'<div class="meta">'+esc(p.repo)+' &middot; '+esc(p.author||'unknown')
          +' &middot; <span class="b '+(p.draft?'b-draft':'b-open')+'">'+(p.draft?'DRAFT':'OPEN')+'</span></div>'
          +'</a>'}).join('');
    }
    function skeleton(){
      document.getElementById('list').innerHTML=
        '<div class="sk"><i class="w25"></i><i class="w60"></i><i class="w40"></i></div>'
        +'<div class="sk"><i class="w25"></i><i class="w60"></i><i class="w40"></i></div>';
    }
    function load(){
      skeleton();
      fetch('/api/pull-requests').then(function(r){return r.json()}).then(function(d){
        render(d.prs||[]);
        document.getElementById('pill').textContent=(d.total_count||0)+' open';
      }).catch(function(e){
        document.getElementById('list').innerHTML='<div class="empty"><b>Unable to load pull requests</b><p>'+esc(e.message)+'</p></div>';
      });
    }
    load();
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# FastAPI APIRouter Definition
# ---------------------------------------------------------------------------
router = APIRouter(tags=["pull-requests"])


@router.get("/api/pull-requests", response_model=PullRequestsResponse)
async def get_pull_requests_data(
    refresh: bool = Query(
        False, description="Bypass in-memory cache and query GitHub API directly"
    ),
    involved: bool = Query(
        True,
        description=(
            "Also include pull requests where the owner is a requested "
            "reviewer or the assignee"
        ),
    ),
):
    """
    Returns every open pull request across the owner's GitHub repositories.

    Falls back to per-repository listings when the GitHub Search API is rate
    limited (common without a token) and degrades to an empty payload with an
    `error` message rather than a 5xx when GitHub is unreachable.
    """
    service = get_pull_request_service()
    return await service.get_pull_requests(refresh=refresh, involved=involved)


@router.get("/pull-requests", response_class=HTMLResponse)
async def get_pull_requests_ui():
    """
    Returns the standalone, mobile-first pull requests dashboard.
    Renders static/pull-requests/index.html if present on disk, otherwise
    serves the built-in HTML fallback.
    """
    if PULL_REQUESTS_HTML_PATH.exists() and PULL_REQUESTS_HTML_PATH.is_file():
        content = PULL_REQUESTS_HTML_PATH.read_text(encoding="utf-8")
        return HTMLResponse(content=content, status_code=200)
    return HTMLResponse(content=FALLBACK_HTML, status_code=200)
