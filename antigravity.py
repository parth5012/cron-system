"""
Antigravity Multi-Account Quota Tracker (Batch 1: classifier).
Mirrors pull_requests.py conventions: env-driven config, pydantic models,
pure parsing utilities. Service + router land in Batch 2/3.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration & Constants
# ---------------------------------------------------------------------------
EXHAUSTED_THRESHOLD = float(os.environ.get("ANTIGRAVITY_EXHAUSTED_THRESHOLD", "0.05"))
DEFAULT_CACHE_TTL = 180.0  # 3 minutes — quotas shift on 5h/weekly windows
FETCH_MODELS_URL = os.environ.get(
    "ANTIGRAVITY_FETCH_MODELS_URL",
    "https://cloudcode-pa.googleapis.com/v1internal:fetchAvailableModels",
)
OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_TOKEN_FILE = os.environ.get(
    "ANTIGRAVITY_TOKEN_FILE", "~/.gemini/antigravity-cli/antigravity-oauth-token"
)


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------
class QuotaEntry(BaseModel):
    model: str
    family: str
    window: str
    remaining: float
    resetTime: Optional[str] = None


class FamilySummary(BaseModel):
    family: str
    window: str
    remaining: float
    resetTime: Optional[str] = None
    exhausted: bool = False
    models: List[str] = Field(default_factory=list)


class AccountSnapshot(BaseModel):
    account_id: str
    families: List[FamilySummary] = Field(default_factory=list)
    models: List[QuotaEntry] = Field(default_factory=list)
    error: Optional[str] = None


class AntigravitySnapshot(BaseModel):
    accounts: List[AccountSnapshot] = Field(default_factory=list)
    cached: bool = False
    timestamp: str
    error: Optional[str] = None


def _clean(value: Any) -> str:
    return str(value or "").strip()


def load_accounts_from_env() -> List[Dict[str, str]]:
    """Read account registry from ANTIGRAVITY_ACCOUNTS_JSON (never logs tokens)."""
    raw = os.environ.get("ANTIGRAVITY_ACCOUNTS_JSON", "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if not isinstance(data, list):
        return []
    accounts: List[Dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        account_id = _clean(item.get("id"))
        project_id = _clean(item.get("projectId") or item.get("project_id"))
        token = _clean(item.get("access_token") or item.get("accessToken"))
        token_file = _clean(item.get("token_file") or item.get("tokenFile"))
        refresh_token = _clean(item.get("refresh_token") or item.get("refreshToken"))
        client_id = _clean(item.get("client_id") or item.get("clientId"))
        client_secret = _clean(item.get("client_secret") or item.get("clientSecret"))
        if not account_id:
            continue
        if not token and not token_file and not refresh_token:
            continue
        entry = {"id": account_id, "projectId": project_id}
        if token:
            entry["access_token"] = token
        if token_file:
            entry["token_file"] = token_file
        if refresh_token:
            entry["refresh_token"] = refresh_token
        if client_id:
            entry["client_id"] = client_id
        if client_secret:
            entry["client_secret"] = client_secret
        accounts.append(entry)
    return accounts


def is_token_expired(expiry: Optional[str], skew_sec: int = 60) -> bool:
    """True when an agy-style RFC3339 expiry is missing, invalid, or nearly past."""
    if not expiry:
        return True
    try:
        moment = datetime.fromisoformat(str(expiry).strip().replace("Z", "+00:00"))
    except ValueError:
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    delta = (moment - datetime.now(timezone.utc)).total_seconds()
    return delta < skew_sec


def load_token_file(path: str) -> Optional[Dict[str, str]]:
    """Read an agy CLI oauth token file. Returns tokens only, never logs them."""
    try:
        data = json.loads(Path(str(path)).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    token = data.get("token") if isinstance(data, dict) else None
    if not isinstance(token, dict):
        return None
    access_token = _clean(token.get("access_token"))
    if not access_token:
        return None
    return {
        "access_token": access_token,
        "refresh_token": _clean(token.get("refresh_token")),
        "expiry": _clean(token.get("expiry")),
    }


async def refresh_access_token(
    client: httpx.AsyncClient, refresh_token: str, client_id: str, client_secret: str
) -> Optional[Dict[str, Any]]:
    """Exchange a refresh token for a fresh access token. Returns None on any failure."""
    if not refresh_token or not client_id:
        return None
    try:
        response = await client.post(
            OAUTH_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    except Exception:
        return None
    if response.status_code != 200:
        return None
    try:
        body = response.json() or {}
    except ValueError:
        return None
    access_token = _clean(body.get("access_token"))
    if not access_token:
        return None
    try:
        lifetime = int(body.get("expires_in") or 3600)
    except (TypeError, ValueError):
        lifetime = 3600
    renewed: Dict[str, Any] = {"access_token": access_token, "lifetime_sec": lifetime}
    rotated = _clean(body.get("refresh_token"))
    if rotated:
        renewed["refresh_token"] = rotated
    return renewed


# ---------------------------------------------------------------------------
# Pure classifier utilities (no I/O, no mutation)
# ---------------------------------------------------------------------------
def classify_family(model_id: str) -> str:
    """Map a model id to its quota family."""
    normalized = (model_id or "").strip().lower()
    if normalized.startswith("gemini-"):
        return "gemini"
    if normalized.startswith("claude-"):
        return "claude"
    if normalized.startswith("gpt-") or "openai" in normalized:
        return "openai"
    return "other"


def bucket_for_family(family: str) -> Dict[str, str]:
    """Return the primary quota window for a family, matching agy CLI semantics."""
    if family == "gemini":
        return {"primary": "weekly", "secondary": "burst"}
    if family in ("claude", "openai"):
        return {"primary": "5h", "secondary": "weekly"}
    return {"primary": "weekly", "secondary": "none"}


def _to_fraction(value: Any) -> Optional[float]:
    try:
        fraction = float(value)
    except (TypeError, ValueError):
        return None
    if 0.0 <= fraction <= 1.0:
        return fraction
    return None


def parse_quota_entry(model_id: str, quota_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize one fetchAvailableModels quotaInfo into a plain dict."""
    if not model_id or not isinstance(quota_info, dict):
        return None
    remaining = _to_fraction(quota_info.get("remainingFraction"))
    if remaining is None:
        return None
    family = classify_family(model_id)
    window = bucket_for_family(family)["primary"]
    reset_time = quota_info.get("resetTime")
    return {
        "model": model_id,
        "family": family,
        "window": window,
        "remaining": remaining,
        "resetTime": str(reset_time) if reset_time else None,
    }


def is_exhausted(remaining: float, threshold: float = EXHAUSTED_THRESHOLD) -> bool:
    """True when remaining quota is below the skip-routing threshold."""
    try:
        return float(remaining) < float(threshold)
    except (TypeError, ValueError):
        return True


def summarize_family(family: str, entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate one family's entries by minimum remaining (most constrained)."""
    relevant = [e for e in (entries or []) if e.get("family") == family]
    if not relevant:
        window = bucket_for_family(family)["primary"]
        return {
            "family": family,
            "window": window,
            "remaining": 0.0,
            "resetTime": None,
            "exhausted": True,
            "models": [],
        }
    ordered = sorted(relevant, key=lambda e: float(e.get("remaining", 0.0)))
    worst = ordered[0]
    latest_reset = max(
        [str(e.get("resetTime") or "") for e in relevant if e.get("resetTime")],
        default=None,
    )
    return {
        "family": family,
        "window": str(worst.get("window") or bucket_for_family(family)["primary"]),
        "remaining": float(worst.get("remaining", 0.0)),
        "resetTime": latest_reset,
        "exhausted": is_exhausted(float(worst.get("remaining", 0.0))),
        "models": [str(e.get("model")) for e in relevant if e.get("model")],
    }


# ---------------------------------------------------------------------------
# Quota service with TTL cache (mirrors PullRequestService)
# ---------------------------------------------------------------------------
class AntigravityService:
    def __init__(self, cache_ttl: float = DEFAULT_CACHE_TTL):
        self.cache_ttl = cache_ttl
        self._lock = threading.Lock()
        self._cached: Optional[AntigravitySnapshot] = None
        self._cached_at: float = 0.0
        self._live_tokens: Dict[str, str] = {}
        self._live_refresh: Dict[str, str] = {}

    def _headers_for(self, access_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "User-Agent": "cron-system-antigravity/1.0",
        }

    def _effective_tokens(self, account: Dict[str, str]) -> Dict[str, str]:
        """Resolve the freshest tokens: live renewal wins, then file, then inline."""
        live = self._live_tokens.get(account["id"])
        if live:
            refresh = self._live_refresh.get(account["id"]) or account.get("refresh_token", "")
            return {"access_token": live, "refresh_token": refresh}
        token_file = account.get("token_file") or (
            os.environ.get("ANTIGRAVITY_TOKEN_FILE", DEFAULT_TOKEN_FILE)
            if not account.get("access_token")
            else ""
        )
        if token_file:
            file_tokens = load_token_file(token_file)
            if file_tokens and file_tokens.get("access_token"):
                return file_tokens
        return {
            "access_token": account.get("access_token", ""),
            "refresh_token": account.get("refresh_token", ""),
        }

    def _client_creds(self, account: Dict[str, str]) -> Dict[str, str]:
        return {
            "client_id": account.get("client_id")
            or os.environ.get("ANTIGRAVITY_OAUTH_CLIENT_ID", ""),
            "client_secret": account.get("client_secret")
            or os.environ.get("ANTIGRAVITY_OAUTH_CLIENT_SECRET", ""),
        }

    async def _post_models(
        self, client: httpx.AsyncClient, account: Dict[str, str], access_token: str
    ) -> httpx.Response:
        return await client.post(
            FETCH_MODELS_URL,
            headers=self._headers_for(access_token),
            json={"project": account.get("projectId") or ""},
        )

    async def _fetch_one(
        self, client: httpx.AsyncClient, account: Dict[str, str]
    ) -> AccountSnapshot:
        tokens = self._effective_tokens(account)
        if not tokens.get("access_token"):
            bootstrapped = await self._try_renew_from_account(client, account)
            if bootstrapped is None:
                return AccountSnapshot(account_id=account["id"], error="no access token available")
            tokens = {"access_token": bootstrapped, "refresh_token": account.get("refresh_token", "")}
        try:
            response = await self._post_models(client, account, tokens["access_token"])
        except Exception as exc:
            return AccountSnapshot(account_id=account["id"], error=f"connect failed: {exc}")
        if response.status_code in (401, 403):
            renewed = await self._try_renew(client, account, tokens)
            if renewed is None:
                return AccountSnapshot(
                    account_id=account["id"],
                    error="upstream 401: token expired and no refresh credentials",
                )
            try:
                response = await self._post_models(client, account, renewed)
            except Exception as exc:
                return AccountSnapshot(account_id=account["id"], error=f"connect failed: {exc}")
        if response.status_code != 200:
            detail = (response.text or "")[:200]
            return AccountSnapshot(
                account_id=account["id"],
                error=f"upstream {response.status_code}: {detail}",
            )
        try:
            payload = response.json() or {}
        except ValueError:
            return AccountSnapshot(account_id=account["id"], error="invalid upstream JSON")
        models = payload.get("models") or {}
        entries: List[QuotaEntry] = []
        raw_entries: List[Dict[str, Any]] = []
        for model_id, info in models.items():
            quota_info = (info or {}).get("quotaInfo") or {}
            parsed = parse_quota_entry(str(model_id), quota_info)
            if parsed is None:
                continue
            raw_entries.append(parsed)
            entries.append(QuotaEntry(**parsed))
        families = [
            FamilySummary(**summarize_family(family, raw_entries))
            for family in ("gemini", "claude", "openai")
            if any(e.get("family") == family for e in raw_entries)
        ]
        return AccountSnapshot(account_id=account["id"], families=families, models=entries)

    async def _try_renew_from_account(
        self, client: httpx.AsyncClient, account: Dict[str, str]
    ) -> Optional[str]:
        """Proactive renewal when no access token is on hand (fresh Vercel setup)."""
        refresh_token = account.get("refresh_token", "")
        creds = self._client_creds(account)
        renewed = await refresh_access_token(
            client, refresh_token, creds["client_id"], creds["client_secret"]
        )
        if renewed is None:
            return None
        fresh = str(renewed["access_token"])
        with self._lock:
            self._live_tokens[account["id"]] = fresh
            if renewed.get("refresh_token"):
                self._live_refresh[account["id"]] = str(renewed["refresh_token"])
        return fresh

    async def _try_renew(
        self, client: httpx.AsyncClient, account: Dict[str, str], tokens: Dict[str, str]
    ) -> Optional[str]:
        """Mint a fresh access token once and cache it in memory. Returns None if impossible."""
        refresh_token = tokens.get("refresh_token") or account.get("refresh_token", "")
        creds = self._client_creds(account)
        renewed = await refresh_access_token(
            client, refresh_token, creds["client_id"], creds["client_secret"]
        )
        if renewed is None:
            return None
        fresh = str(renewed["access_token"])
        with self._lock:
            self._live_tokens[account["id"]] = fresh
            if renewed.get("refresh_token"):
                self._live_refresh[account["id"]] = str(renewed["refresh_token"])
        return fresh

    async def _fetch_snapshot(self) -> AntigravitySnapshot:
        accounts = load_accounts_from_env()
        now_iso = datetime.now(timezone.utc).isoformat()
        if not accounts:
            return AntigravitySnapshot(
                accounts=[], cached=False, timestamp=now_iso, error="no accounts configured"
            )
        timeout = httpx.Timeout(15.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            snapshots = [await self._fetch_one(client, acc) for acc in accounts]
        errors = [s.error for s in snapshots if s.error]
        return AntigravitySnapshot(
            accounts=snapshots,
            cached=False,
            timestamp=now_iso,
            error="; ".join(errors) if errors else None,
        )

    async def get_snapshot(self, refresh: bool = False) -> AntigravitySnapshot:
        now = time.time()
        with self._lock:
            if (
                not refresh
                and self._cached is not None
                and (now - self._cached_at) < self.cache_ttl
            ):
                cached_copy = self._cached.model_copy()
                cached_copy.cached = True
                return cached_copy
        fresh = await self._fetch_snapshot()
        with self._lock:
            self._cached = fresh
            self._cached_at = time.time()
        return fresh


_antigravity_service = AntigravityService()


def get_antigravity_service() -> AntigravityService:
    return _antigravity_service


# ---------------------------------------------------------------------------
# OmniRoute sync (best-effort: ensures 5h + weekly rows exist per account)
# ---------------------------------------------------------------------------
OMNIROUTE_BASE_URL = os.environ.get("OMNIROUTE_BASE_URL", "http://localhost:20128").rstrip("/")
OMNIROUTE_SYNC_ENABLED = os.environ.get("OMNIROUTE_SYNC_ENABLED", "false").lower() == "true"
ANTIGRAVITY_HTML_PATH = Path(__file__).parent / "static" / "antigravity" / "index.html"


def build_omniroute_limits(snapshot: AntigravitySnapshot) -> List[Dict[str, Any]]:
    """Build token-limit rows ensuring both 5h and weekly windows exist per account."""
    rows: List[Dict[str, Any]] = []
    seen = set()
    for account in snapshot.accounts:
        windows = {f.window for f in account.families} or {"5h", "weekly"}
        for window in sorted(windows):
            key = (account.account_id, window)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "apiKeyId": account.account_id,
                    "scopeType": "provider",
                    "scopeValue": "antigravity",
                    "tokenLimit": 1000000,
                    "resetInterval": window,
                    "enabled": True,
                }
            )
    return rows


async def sync_to_omniroute(snapshot: AntigravitySnapshot) -> Dict[str, Any]:
    """POST limit rows to OmniRoute. Never raises; returns a summary dict."""
    rows = build_omniroute_limits(snapshot)
    if not OMNIROUTE_SYNC_ENABLED:
        return {"synced": 0, "skipped": "OMNIROUTE_SYNC_ENABLED=false", "rows": rows}
    ok, errors = 0, []
    timeout = httpx.Timeout(8.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for row in rows:
            try:
                response = await client.post(
                    f"{OMNIROUTE_BASE_URL}/api/usage/token-limits", json=row
                )
                if response.status_code in (200, 201):
                    ok += 1
                else:
                    errors.append(f"{row['resetInterval']}: {response.status_code}")
            except Exception as exc:
                errors.append(f"{row['resetInterval']}: {exc}")
    summary: Dict[str, Any] = {"synced": ok, "total": len(rows)}
    if errors:
        summary["errors"] = errors
    return summary


# ---------------------------------------------------------------------------
# Dashboard HTML (fallback served when static/antigravity/index.html is absent)
# ---------------------------------------------------------------------------
FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Antigravity Limits | Cron System</title>
  <style>
    :root { --bg:#f8f9fa; --card:#fff; --text:#18181b; --muted:#71717a; --border:#e4e4e7; --primary:#2563eb; --warn:#d97706; --bad:#dc2626; --ok:#059669; }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; padding-bottom: 96px; }
    .wrap { max-width: 900px; margin: 0 auto; padding: 18px 16px; }
    .top { display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 14px; }
    h1 { font-size: 1.3rem; font-weight: 700; }
    .sub { font-size: .82rem; color: var(--muted); }
    .pill { font-size: .74rem; padding: 6px 12px; border: 1px solid var(--border); border-radius: 99px; background: var(--card); color: var(--muted); }
    .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px; margin-bottom: 10px; }
    .fam { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px 0; border-top: 1px solid var(--border); font-size: .85rem; }
    .fam:first-of-type { border-top: none; }
    .bar { height: 8px; border-radius: 99px; background: var(--border); overflow: hidden; margin-top: 6px; }
    .bar i { display: block; height: 100%; background: var(--ok); }
    .b { font-size: .68rem; font-weight: 700; padding: 2px 8px; border-radius: 99px; }
    .b-5h { background: rgba(37,99,235,.14); color: var(--primary); }
    .b-weekly { background: rgba(217,119,6,.15); color: var(--warn); }
    .b-out { background: rgba(220,38,38,.14); color: var(--bad); }
    .b-ok { background: rgba(5,150,105,.14); color: var(--ok); }
    .btn { appearance: none; border: 1px solid var(--border); border-radius: 8px; background: var(--primary); color: #fff; padding: 8px 12px; font-size: .85em; cursor: pointer; }
    .btn.ghost { background: transparent; color: var(--text); }
    .empty { text-align: center; color: var(--muted); padding: 48px 20px; border: 1px dashed var(--border); border-radius: 12px; background: var(--card); }
    .bnav { position: fixed; left: 0; right: 0; bottom: 0; display: flex; background: var(--card); border-top: 1px solid var(--border); z-index: 50; padding-bottom: env(safe-area-inset-bottom, 16px); }
    .bnav a { flex: 1; text-align: center; text-decoration: none; color: var(--muted); font-size: .7rem; font-weight: 600; padding: 12px 0; min-height: 48px; }
    .bnav a.on { color: var(--primary); }
    .bnav span { display: block; font-size: 1.15rem; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top">
      <div><h1>&#9889; Antigravity Limits</h1><div class="sub">5h + weekly per account, split by family (agy CLI semantics)</div></div>
      <span class="pill" id="pill">Loading...</span>
    </div>
    <div style="display:flex;gap:8px;margin-bottom:12px">
      <button class="btn" id="refreshBtn">Refresh now</button>
      <button class="btn ghost" id="syncBtn">Sync OmniRoute rows</button>
    </div>
    <div id="syncMsg" class="sub" style="margin-bottom:12px"></div>
    <div id="list"></div>
  </div>
  <nav class="bnav">
    <a href="/wayfinder"><span>&#128506;</span>Wayfinder</a>
    <a href="/pull-requests"><span>&#128256;</span>PRs</a>
    <a href="/antigravity" class="on"><span>&#9889;</span>Limits</a>
    <a href="/pwa/"><span>&#128193;</span>Content</a>
  </nav>
  <script>
    function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
    function pct(r){return Math.round(Number(r||0)*100)}
    function bar(r){var p=pct(r);var c=p<5?'var(--bad)':(p<25?'var(--warn)':'var(--ok)');return '<div class="bar"><i style="width:'+p+'%;background:'+c+'"></i></div>'}
    function famRow(f){
      var badge=f.exhausted?'<span class="b b-out">OUT</span>':'<span class="b b-ok">'+pct(f.remaining)+'%</span>';
      return '<div class="fam"><div style="flex:1"><b>'+esc(f.family)+'</b> <span class="b b-'+esc(f.window)+'">'+esc(f.window)+'</span>'
        +'<div class="sub">reset: '+esc(f.resetTime||'n/a')+' &middot; '+esc((f.models||[]).join(', '))+'</div>'+bar(f.remaining)+'</div><div>'+badge+'</div></div>';
    }
    function render(d){
      var list=document.getElementById('list');
      var accs=d.accounts||[];
      document.getElementById('pill').textContent=accs.length+' accounts'+(d.cached?' (cached)':'')+(d.error?' — '+d.error:'');
      if(!accs.length){list.innerHTML='<div class="empty"><b>No accounts configured.</b><p>Set ANTIGRAVITY_ACCOUNTS_JSON on the server.</p></div>';return}
      list.innerHTML=accs.map(function(a){
        return '<div class="card"><b>'+esc(a.account_id)+'</b>'
          +(a.error?'<div class="sub">error: '+esc(a.error)+'</div>':'')
          +(a.families||[]).map(famRow).join('')+'</div>';
      }).join('');
    }
    function load(refresh){
      document.getElementById('pill').textContent='Loading...';
      fetch('/api/antigravity/limits'+(refresh?'?refresh=true': '')).then(function(r){return r.json()}).then(render)
        .catch(function(e){document.getElementById('list').innerHTML='<div class="empty"><b>Unable to load</b><p>'+esc(e.message)+'</p></div>'});
    }
    document.getElementById('refreshBtn').onclick=function(){load(true)};
    document.getElementById('syncBtn').onclick=function(){
      document.getElementById('syncMsg').textContent='Syncing...';
      fetch('/api/antigravity/sync',{method:'POST'}).then(function(r){return r.json()}).then(function(d){
        document.getElementById('syncMsg').textContent='OmniRoute sync: '+JSON.stringify(d);
      }).catch(function(e){document.getElementById('syncMsg').textContent='Sync failed: '+e.message});
    };
    load(false);
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# FastAPI APIRouter Definition
# ---------------------------------------------------------------------------
router = APIRouter(tags=["antigravity"])


@router.get("/api/antigravity/limits", response_model=AntigravitySnapshot)
async def get_antigravity_limits(
    refresh: bool = Query(False, description="Bypass TTL cache and poll upstream now"),
):
    """Per-account 5h + weekly remaining split by family (gemini/claude/openai)."""
    service = get_antigravity_service()
    return await service.get_snapshot(refresh=refresh)


@router.get("/api/antigravity/omniroute-preview")
async def get_omniroute_preview():
    """Show the token-limit rows that would be synced to OmniRoute (no writes)."""
    service = get_antigravity_service()
    snapshot = await service.get_snapshot(refresh=False)
    return {"limits": build_omniroute_limits(snapshot), "sync_enabled": OMNIROUTE_SYNC_ENABLED}


@router.post("/api/antigravity/sync")
async def post_antigravity_sync():
    """Refresh quotas then best-effort sync 5h/weekly rows to OmniRoute."""
    service = get_antigravity_service()
    snapshot = await service.get_snapshot(refresh=True)
    result = await sync_to_omniroute(snapshot)
    return {**result, "timestamp": snapshot.timestamp}


@router.get("/antigravity", response_class=HTMLResponse)
async def get_antigravity_ui():
    """Mobile-first limits dashboard inside cron-system (no separate site)."""
    if ANTIGRAVITY_HTML_PATH.exists() and ANTIGRAVITY_HTML_PATH.is_file():
        return HTMLResponse(content=ANTIGRAVITY_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(content=FALLBACK_HTML, status_code=200)
