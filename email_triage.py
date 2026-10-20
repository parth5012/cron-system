"""
Email Triage Feature Backend Service & Endpoints for Cron System.
Integrates Himalaya CLI + TypeSafe Jev / Clef System One Decision Models.
"""

import asyncio
import json
import logging
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Load Environment & Setup Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent

def _resolve_data_dir() -> Path:
    candidates = []
    if os.environ.get("CRON_SYSTEM_DATA_DIR"):
        candidates.append(Path(os.environ["CRON_SYSTEM_DATA_DIR"]))
    try:
        candidates.append(Path.home() / ".local" / "share" / "cron-system")
    except Exception:
        pass
    candidates.append(Path("/tmp/cron-system"))
    candidates.append(Path("/tmp"))

    for c in candidates:
        try:
            c.mkdir(parents=True, exist_ok=True)
            return c
        except Exception:
            continue
    return Path("/tmp")

DATA_DIR = _resolve_data_dir()
DB_PATH = DATA_DIR / "email_triage.db"
STATIC_DIR = BASE_DIR / "static" / "email-triage"
HTML_INDEX_PATH = STATIC_DIR / "index.html"

# Load environment from .env files
if load_dotenv:
    try:
        load_dotenv(BASE_DIR / ".env")
        if not os.getenv("CLOUDFLARE_API_TOKEN"):
            p_warden = Path.home() / "projects" / "warden" / "src" / "warden" / ".env"
            if p_warden.exists():
                load_dotenv(p_warden)
        if not os.getenv("OPENROUTER_API_KEY"):
            p1 = Path.home() / "projects" / "orca-marine-intelligence" / ".env"
            if p1.exists():
                load_dotenv(p1)
        if not os.getenv("OPENROUTER_API_KEY"):
            p2 = Path.home() / ".hermes" / ".env"
            if p2.exists():
                load_dotenv(p2)
    except Exception:
        pass

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api").rstrip("/")
CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "") or os.getenv("CLEF_API_TOKEN", "")
CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "") or os.getenv("CLEF_ACCOUNT_ID", "")
DEFAULT_PROVIDER = os.getenv(
    "DECISION_PROVIDER",
    "cloudflare" if (CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID) else "openrouter"
).lower()
DEFAULT_MODEL = os.getenv(
    "DECISION_MODEL",
    "@cf/cloudflare/clef-flash" if DEFAULT_PROVIDER == "cloudflare" else "typesafe/jev-1.13"
)
HIMALAYA_BIN = os.getenv("HIMALAYA_BIN", "himalaya")

logger = logging.getLogger("email_triage")
logger.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# Database Management
# ---------------------------------------------------------------------------
def get_db_connection() -> sqlite3.Connection:
    try:
        conn = sqlite3.connect(str(DB_PATH))
    except Exception:
        conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    try:
        with get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_triage_cache (
                    message_id TEXT PRIMARY KEY,
                    subject TEXT,
                    sender_name TEXT,
                    sender_email TEXT,
                    date TEXT,
                    size INTEGER,
                    category TEXT,
                    is_irrelevant_prob REAL,
                    urgency_score REAL,
                    action_required_prob REAL,
                    summary TEXT,
                    archived INTEGER DEFAULT 0,
                    categorized_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_triage_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT,
                    message_ids TEXT,
                    details TEXT,
                    timestamp TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS email_triage_allowlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT UNIQUE NOT NULL,
                    note TEXT,
                    created_at TEXT
                )
            """)
            # Pre-seed default essential patterns if table empty
            cur = conn.execute("SELECT COUNT(*) AS cnt FROM email_triage_allowlist")
            if cur.fetchone()["cnt"] == 0:
                defaults = [
                    ("flyrank.ai", "Internship Engineering"),
                    ("github.com", "GitHub & CI/CD Notifications"),
                    ("truelancer.com", "Freelance Client Leads"),
                ]
                conn.executemany(
                    "INSERT INTO email_triage_allowlist (pattern, note, created_at) VALUES (?, ?, ?)",
                    [(pat, note, datetime.now(timezone.utc).isoformat()) for pat, note in defaults]
                )
            conn.commit()
    except Exception as exc:
        logger.warning("Could not initialize email_triage database: %s", exc)

init_db()

def get_all_allowlist_patterns() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id, pattern, note, created_at FROM email_triage_allowlist ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]

def is_allowlisted(sender_email: str, sender_name: str, patterns: Optional[List[str]] = None) -> bool:
    if patterns is None:
        with get_db_connection() as conn:
            rows = conn.execute("SELECT pattern FROM email_triage_allowlist").fetchall()
            patterns = [r["pattern"].lower() for r in rows]
    
    sender_email_lower = (sender_email or "").lower()
    sender_name_lower = (sender_name or "").lower()

    for pat in patterns:
        pat_clean = pat.strip().lower().lstrip("@")
        if pat_clean and (pat_clean in sender_email_lower or pat_clean in sender_name_lower):
            return True
    return False

# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------
class EmailAddress(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None

class EmailItem(BaseModel):
    id: str
    subject: str = "(No Subject)"
    sender_name: str = "Unknown"
    sender_email: str = ""
    date: Optional[str] = None
    size: Optional[int] = None
    flags: List[str] = Field(default_factory=list)
    unread: bool = False
    allowlisted: bool = False
    
    # Categorization outputs
    categorized: bool = False
    category: Optional[str] = None
    is_irrelevant_prob: Optional[float] = None
    urgency_score: Optional[float] = None
    action_required_prob: Optional[float] = None
    summary: Optional[str] = None
    archived: bool = False
    categorized_at: Optional[str] = None

class EmailListResponse(BaseModel):
    emails: List[EmailItem]
    total: int
    uncategorized_count: int
    irrelevant_count: int
    action_required_count: int
    timestamp: str

class AllowlistRule(BaseModel):
    id: int
    pattern: str
    note: Optional[str] = None
    created_at: Optional[str] = None

class AllowlistCreateRequest(BaseModel):
    pattern: str
    note: Optional[str] = ""

class AllowlistResponse(BaseModel):
    rules: List[AllowlistRule]
    total: int

class CategorizeRequest(BaseModel):
    email_ids: Optional[List[str]] = None
    force_refresh: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None

class CategorizeResponse(BaseModel):
    categorized_count: int
    results: Dict[str, Dict[str, Any]]
    duration_sec: float

class ArchiveRequest(BaseModel):
    message_ids: List[str]

class ArchiveResponse(BaseModel):
    success: bool
    archived_count: int
    message_ids: List[str]
    errors: List[str] = Field(default_factory=list)

class EmailBodyResponse(BaseModel):
    id: str
    subject: str
    sender: str
    body_text: str
    is_html: bool = False

# ---------------------------------------------------------------------------
# Himalaya Helpers
# ---------------------------------------------------------------------------
def run_himalaya_command(args: List[str], timeout: float = 30.0) -> Dict[str, Any]:
    cmd = [HIMALAYA_BIN] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            logger.error("Himalaya command failed: %s -> %s", " ".join(cmd), proc.stderr)
            raise RuntimeError(f"Himalaya failed ({proc.returncode}): {proc.stderr.strip()}")
        return {"stdout": proc.stdout, "stderr": proc.stderr}
    except FileNotFoundError:
        raise RuntimeError(f"Himalaya binary not found at '{HIMALAYA_BIN}'")

def fetch_envelopes_from_himalaya(limit: int = 50) -> List[Dict[str, Any]]:
    res = run_himalaya_command(["envelope", "list", "-s", str(limit), "--json"])
    data = json.loads(res["stdout"])
    return data.get("envelopes", [])

def move_messages_to_archive(message_ids: List[str]) -> Dict[str, Any]:
    if not message_ids:
        return {"archived": [], "errors": []}
    
    # Himalaya move to [Gmail]/All Mail
    archived = []
    errors = []
    
    # Batch move or move individually for fault tolerance
    for mid in message_ids:
        try:
            cmd = ["message", "move", "--to", "[Gmail]/All Mail", str(mid)]
            run_himalaya_command(cmd, timeout=15.0)
            archived.append(str(mid))
        except Exception as e:
            errors.append(f"Failed to move {mid}: {str(e)}")
            
    # Update SQLite records
    if archived:
        with get_db_connection() as conn:
            conn.executemany(
                "UPDATE email_triage_cache SET archived = 1 WHERE message_id = ?",
                [(mid,) for mid in archived]
            )
            conn.execute(
                "INSERT INTO email_triage_audit_log (action, message_ids, details, timestamp) VALUES (?, ?, ?, ?)",
                ("archive", json.dumps(archived), f"Moved to [Gmail]/All Mail. Errors: {len(errors)}", datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
            
    return {"archived": archived, "errors": errors}

def extract_email_body_text(message_id: str) -> Dict[str, Any]:
    res = run_himalaya_command(["message", "read", str(message_id), "--json"], timeout=20.0)
    data = json.loads(res["stdout"])
    
    subject = "(No Subject)"
    sender = "Unknown"
    body_text = ""
    is_html = False
    
    parts = data.get("parts", [])
    for part in parts:
        headers = part.get("headers", [])
        for h in headers:
            name = h.get("name", "")
            val = h.get("value", {})
            if isinstance(name, str) and name.lower() == "subject":
                subject = val.get("Text", subject)
            elif isinstance(name, str) and name.lower() == "from":
                addr_list = val.get("Address", {}).get("List", [])
                if addr_list:
                    sender = f"{addr_list[0].get('name') or ''} <{addr_list[0].get('address') or ''}>".strip()
        
        # Check text body
        body = part.get("body", {})
        if "Text" in body and not body_text:
            body_text = body["Text"]
            is_html = False
        elif "Html" in body and not body_text:
            # Strip simple html tags if plain text wasn't found
            raw_html = body["Html"]
            clean_text = re.sub(r"<style.*?</style>", "", raw_html, flags=re.DOTALL)
            clean_text = re.sub(r"<script.*?</script>", "", clean_text, flags=re.DOTALL)
            clean_text = re.sub(r"<[^>]+>", " ", clean_text)
            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            body_text = clean_text
            is_html = True

    return {
        "id": str(message_id),
        "subject": subject,
        "sender": sender,
        "body_text": body_text or "(No body content found)",
        "is_html": is_html
    }

# ---------------------------------------------------------------------------
# Decision Model (Jev System One) Categorization
# ---------------------------------------------------------------------------
QUESTIONS_TAXONOMY = {
    "is_irrelevant": {
        "type": "noul",
        "instructions": (
            "Is this promotional, cold sales pitch, marketing discount, ecommerce deal, "
            "automated marketing blast, or irrelevant promotional email that can be safely archived?"
        ),
    },
    "category": {
        "type": "choice",
        "instructions": "Classify the email into its primary operational bucket for Parth",
        "criteria": {
            "work": "Engineering, GitHub PR/issue notifications, coding tasks, Flyrank internship, development",
            "freelance": "Freelance client leads, Truelancer/Upwork gigs, project inquiries, inbound contracting",
            "personal": "Personal 1-on-1 conversations, professors, university academics, direct outreach",
            "newsletter": "High-value tech digests, Substack, AI publications, engineering blogs",
            "transactional": "Order receipts, delivery updates, OTPs, invoices, banking, security alerts",
            "irrelevant": "Promotional sales, marketing blasts, discount coupons, shopping deals, cold pitches"
        }
    },
    "urgency": {
        "type": "score",
        "instructions": "Urgency level of required attention or response",
        "criteria": ["Low", "Medium", "High", "Critical"]
    },
    "action_required": {
        "type": "noul",
        "instructions": "Does this email require a direct action, follow-up, or reply from Parth?"
    }
}

def _parse_noul(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return min(1.0, max(0.0, float(val)))
    if isinstance(val, dict):
        for k in ("noul", "probability", "prob", "score"):
            if k in val and isinstance(val[k], (int, float)):
                return min(1.0, max(0.0, float(val[k])))
        probs = val.get("probabilities") or val.get("probs")
        if isinstance(probs, dict):
            for k in ("yes", "true", "positive", "1"):
                if k in probs and isinstance(probs[k], (int, float)):
                    return min(1.0, max(0.0, float(probs[k])))
    return 0.0

def _parse_choice(val: Any, default: str = "irrelevant") -> str:
    if val is None:
        return default
    if isinstance(val, str):
        return val
    if isinstance(val, dict):
        for k in ("choice", "selected", "answer", "value"):
            if k in val and isinstance(val[k], str):
                return val[k]
        probs = val.get("probabilities") or val.get("probs")
        if isinstance(probs, dict) and probs:
            try:
                return str(max(probs.items(), key=lambda kv: kv[1])[0])
            except Exception:
                pass
    return default

def _parse_score(val: Any) -> float:
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, dict):
        for k in ("score", "rating", "value"):
            if k in val and isinstance(val[k], (int, float)):
                return float(val[k])
    return 0.0

async def classify_single_email(
    http_client: httpx.AsyncClient,
    email: Dict[str, Any],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
    cloudflare_token: Optional[str] = None,
    cloudflare_account_id: Optional[str] = None,
) -> Dict[str, Any]:
    subject = email.get("subject", "")
    from_info = email.get("from", [{}])
    sender_name = from_info[0].get("name", "") if from_info else ""
    sender_email = from_info[0].get("email", "") if from_info else ""
    
    state = {
        "subject": subject,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "date": email.get("date", "")
    }

    # Resolve provider and model
    selected_provider = (provider or "").lower()
    selected_model = model or ""

    if not selected_provider:
        if selected_model.startswith("@cf/") or "clef" in selected_model.lower():
            selected_provider = "cloudflare"
        elif "jev" in selected_model.lower():
            selected_provider = "openrouter"
        else:
            selected_provider = DEFAULT_PROVIDER

    if selected_provider == "cloudflare":
        if not selected_model or "jev" in selected_model.lower():
            selected_model = "@cf/cloudflare/clef-flash"
    elif selected_provider == "openrouter":
        if not selected_model or "clef" in selected_model.lower():
            selected_model = "typesafe/jev-1.13"

    async def _call_cloudflare_clef(m_tag: str) -> Dict[str, Any]:
        cf_tok = cloudflare_token or CLOUDFLARE_API_TOKEN
        cf_acct = cloudflare_account_id or CLOUDFLARE_ACCOUNT_ID
        if not cf_tok or not cf_acct:
            raise ValueError("CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID required for Clef")
        
        if m_tag in ("clef-flash", "clef-9b", "@cf/cloudflare/clef-flash"):
            tag = "@cf/cloudflare/clef-flash"
            selector = "clef-flash"
        elif m_tag in ("clef", "clef-27b", "@cf/cloudflare/clef"):
            tag = "@cf/cloudflare/clef"
            selector = "clef"
        else:
            tag = m_tag if m_tag.startswith("@cf/") else f"@cf/cloudflare/{m_tag}"
            selector = "clef-flash" if "flash" in tag else "clef"

        url = f"https://api.cloudflare.com/client/v4/accounts/{cf_acct}/ai/run/{tag}"
        headers = {
            "Authorization": f"Bearer {cf_tok}",
            "Content-Type": "application/json"
        }
        body = {
            "model": selector,
            "state": state,
            "questions": QUESTIONS_TAXONOMY
        }
        resp = await http_client.post(url, json=body, headers=headers, timeout=20.0)
        if resp.status_code != 200:
            raise RuntimeError(f"Cloudflare Workers AI error ({resp.status_code}): {resp.text}")
        raw = resp.json()
        if not raw.get("success", True):
            raise RuntimeError(f"Workers AI error payload: {raw.get('errors', raw)}")
        res_dict = raw.get("result", raw)
        return res_dict.get("answers", res_dict)

    async def _call_openrouter_jev(m_name: str) -> Dict[str, Any]:
        key = api_key or OPENROUTER_API_KEY
        if not key:
            raise ValueError("OPENROUTER_API_KEY is required for Jev")
        url = f"{OPENROUTER_BASE_URL}/v1/systemone"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"
        }
        body = {
            "model": m_name,
            "state": state,
            "questions": QUESTIONS_TAXONOMY
        }
        resp = await http_client.post(url, json=body, headers=headers, timeout=20.0)
        if resp.status_code != 200:
            raise RuntimeError(f"OpenRouter Decision API error ({resp.status_code}): {resp.text}")
        data = resp.json()
        return data.get("answers", data)

    answers: Dict[str, Any] = {}
    used_provider = selected_provider
    used_model = selected_model

    try:
        if selected_provider == "cloudflare":
            answers = await _call_cloudflare_clef(selected_model)
        elif selected_provider == "openrouter":
            answers = await _call_openrouter_jev(selected_model)
        elif selected_provider == "auto":
            if CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID:
                try:
                    used_provider = "cloudflare"
                    used_model = "@cf/cloudflare/clef-flash"
                    answers = await _call_cloudflare_clef(used_model)
                except Exception as cf_err:
                    logger.warning("Clef failed in auto cascade: %s. Falling back to OpenRouter Jev.", cf_err)
                    used_provider = "openrouter"
                    used_model = "typesafe/jev-1.13"
                    answers = await _call_openrouter_jev(used_model)
            else:
                used_provider = "openrouter"
                used_model = "typesafe/jev-1.13"
                answers = await _call_openrouter_jev(used_model)
        else:
            raise ValueError(f"Unknown decision provider: {selected_provider}")

        is_irr = _parse_noul(answers.get("is_irrelevant"))
        cat = _parse_choice(answers.get("category"), default="irrelevant")
        urg = _parse_score(answers.get("urgency"))
        act = _parse_noul(answers.get("action_required"))

        # Enforce allowlist protection: bypass irrelevance marking
        if is_allowlisted(sender_email, sender_name):
            is_irr = 0.0
            if cat == "irrelevant":
                cat = "work"

        return {
            "message_id": str(email.get("id")),
            "category": cat,
            "is_irrelevant_prob": is_irr,
            "urgency_score": urg,
            "action_required_prob": act,
            "categorized_at": datetime.now(timezone.utc).isoformat(),
            "provider": used_provider,
            "model": used_model
        }
    except Exception as e:
        logger.exception("Classification exception for %s", email.get("id"))
        return {"error": str(e), "message_id": str(email.get("id"))}

# ---------------------------------------------------------------------------
# Router & Endpoints
# ---------------------------------------------------------------------------
router = APIRouter(tags=["email-triage"])

@router.get("/api/email-triage/emails", response_model=EmailListResponse)
async def list_recent_emails(
    limit: int = Query(50, ge=1, le=100),
    refresh: bool = Query(False, description="Force fetch fresh envelopes from Himalaya")
):
    """
    Fetches the 50 most recent emails via Himalaya IMAP and merges with local triage cache.
    """
    try:
        envelopes = fetch_envelopes_from_himalaya(limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch emails: {str(e)}")

    # Query cached triage results and allowlist patterns
    cached_map: Dict[str, Dict[str, Any]] = {}
    allow_patterns: List[str] = []
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM email_triage_cache")
        for row in cursor.fetchall():
            cached_map[str(row["message_id"])] = dict(row)
        rows_al = conn.execute("SELECT pattern FROM email_triage_allowlist").fetchall()
        allow_patterns = [r["pattern"].lower() for r in rows_al]

    emails: List[EmailItem] = []
    uncat = 0
    irrel = 0
    action_req = 0

    for env in envelopes:
        mid = str(env.get("id", ""))
        from_list = env.get("from", [])
        s_name = from_list[0].get("name") if from_list else "Unknown"
        s_email = from_list[0].get("email") if from_list else ""
        flags = env.get("flags", [])
        unread = "*" not in flags and "seen" not in [f.lower() for f in flags]

        matched_allowlist = is_allowlisted(s_email, s_name, allow_patterns)

        cached = cached_map.get(mid)
        if cached:
            is_irr_prob = cached.get("is_irrelevant_prob")
            act_prob = cached.get("action_required_prob")
            cat = cached.get("category")
            
            if matched_allowlist:
                is_irr_prob = 0.0
                if cat == "irrelevant":
                    cat = "work"
            
            if is_irr_prob is not None and is_irr_prob >= 0.70:
                irrel += 1
            if act_prob is not None and act_prob >= 0.60:
                action_req += 1

            emails.append(EmailItem(
                id=mid,
                subject=env.get("subject") or "(No Subject)",
                sender_name=s_name or s_email or "Unknown",
                sender_email=s_email or "",
                date=env.get("date"),
                size=env.get("size"),
                flags=flags,
                unread=unread,
                allowlisted=matched_allowlist,
                categorized=True,
                category=cat,
                is_irrelevant_prob=is_irr_prob,
                urgency_score=cached.get("urgency_score"),
                action_required_prob=act_prob,
                summary=cached.get("summary"),
                archived=bool(cached.get("archived", 0)),
                categorized_at=cached.get("categorized_at")
            ))
        else:
            uncat += 1
            emails.append(EmailItem(
                id=mid,
                subject=env.get("subject") or "(No Subject)",
                sender_name=s_name or s_email or "Unknown",
                sender_email=s_email or "",
                date=env.get("date"),
                size=env.get("size"),
                flags=flags,
                unread=unread,
                allowlisted=matched_allowlist,
                categorized=False,
                archived=False
            ))

    return EmailListResponse(
        emails=emails,
        total=len(emails),
        uncategorized_count=uncat,
        irrelevant_count=irrel,
        action_required_count=action_req,
        timestamp=datetime.now(timezone.utc).isoformat()
    )

@router.post("/api/email-triage/categorize", response_model=CategorizeResponse)
async def categorize_emails(req: CategorizeRequest):
    """
    Triggers System One categorization across emails via Cloudflare Clef or TypeSafe Jev.
    """
    target_provider = (req.provider or DEFAULT_PROVIDER).lower()
    target_model = req.model or (
        DEFAULT_MODEL if req.provider is None else (
            "@cf/cloudflare/clef-flash" if target_provider == "cloudflare" else "typesafe/jev-1.13"
        )
    )

    if target_provider == "cloudflare" and not (CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID):
        raise HTTPException(
            status_code=500,
            detail="CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID must be configured in environment or cron-system/.env"
        )
    if target_provider == "openrouter" and not OPENROUTER_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="OPENROUTER_API_KEY is not configured in environment or cron-system/.env"
        )
    if target_provider == "auto" and not ((CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID) or OPENROUTER_API_KEY):
        raise HTTPException(
            status_code=500,
            detail="Neither Cloudflare (Clef) nor OpenRouter (Jev) credentials are configured"
        )

    # 1. Fetch current envelopes to get metadata
    envelopes = fetch_envelopes_from_himalaya(limit=50)
    target_envelopes = envelopes

    if req.email_ids:
        ids_set = {str(i) for i in req.email_ids}
        target_envelopes = [e for e in envelopes if str(e.get("id")) in ids_set]
    elif not req.force_refresh:
        # Check SQLite cache to only categorize uncategorized
        with get_db_connection() as conn:
            rows = conn.execute("SELECT message_id FROM email_triage_cache WHERE category IS NOT NULL").fetchall()
            done_ids = {str(r["message_id"]) for r in rows}
            target_envelopes = [e for e in envelopes if str(e.get("id")) not in done_ids]

    if not target_envelopes:
        return CategorizeResponse(
            categorized_count=0,
            results={},
            duration_sec=0.0
        )

    t0 = time.time()
    semaphore = asyncio.Semaphore(10)

    async def sem_task(client, env):
        async with semaphore:
            return await classify_single_email(
                http_client=client,
                email=env,
                api_key=OPENROUTER_API_KEY,
                model=target_model,
                provider=target_provider,
                cloudflare_token=CLOUDFLARE_API_TOKEN,
                cloudflare_account_id=CLOUDFLARE_ACCOUNT_ID
            )

    async with httpx.AsyncClient(timeout=25.0) as client:
        classified = await asyncio.gather(*(sem_task(client, e) for e in target_envelopes))

    # Persist results in SQLite
    results_map: Dict[str, Dict[str, Any]] = {}
    db_records = []
    now_iso = datetime.now(timezone.utc).isoformat()

    env_by_id = {str(e.get("id")): e for e in target_envelopes}

    for item in classified:
        if "error" in item:
            continue
        mid = item["message_id"]
        results_map[mid] = item
        env = env_by_id.get(mid, {})
        from_list = env.get("from", [])
        s_name = from_list[0].get("name") if from_list else ""
        s_email = from_list[0].get("email") if from_list else ""

        db_records.append((
            mid,
            env.get("subject", ""),
            s_name,
            s_email,
            env.get("date", ""),
            env.get("size", 0),
            item.get("category", ""),
            item.get("is_irrelevant_prob", 0.0),
            item.get("urgency_score", 0.0),
            item.get("action_required_prob", 0.0),
            "",
            0,
            now_iso
        ))

    if db_records:
        with get_db_connection() as conn:
            conn.executemany("""
                INSERT INTO email_triage_cache (
                    message_id, subject, sender_name, sender_email, date, size,
                    category, is_irrelevant_prob, urgency_score, action_required_prob,
                    summary, archived, categorized_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    category = excluded.category,
                    is_irrelevant_prob = excluded.is_irrelevant_prob,
                    urgency_score = excluded.urgency_score,
                    action_required_prob = excluded.action_required_prob,
                    categorized_at = excluded.categorized_at
            """, db_records)
            conn.commit()

    duration = time.time() - t0
    return CategorizeResponse(
        categorized_count=len(results_map),
        results=results_map,
        duration_sec=round(duration, 2)
    )

@router.post("/api/email-triage/archive", response_model=ArchiveResponse)
async def archive_emails(req: ArchiveRequest):
    """
    Archives given message IDs by moving them to [Gmail]/All Mail via Himalaya.
    """
    if not req.message_ids:
        return ArchiveResponse(success=True, archived_count=0, message_ids=[])

    res = move_messages_to_archive(req.message_ids)
    return ArchiveResponse(
        success=len(res["errors"]) == 0,
        archived_count=len(res["archived"]),
        message_ids=res["archived"],
        errors=res["errors"]
    )

@router.get("/api/email-triage/email/{message_id}/body", response_model=EmailBodyResponse)
async def get_email_body(message_id: str):
    """
    Reads email body text/HTML summary via Himalaya for quick snippet inspection.
    """
    try:
        body_data = extract_email_body_text(message_id)
        return EmailBodyResponse(**body_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read email {message_id}: {str(e)}")

# ---------------------------------------------------------------------------
# Allowlist Endpoints
# ---------------------------------------------------------------------------
@router.get("/api/email-triage/allowlist", response_model=AllowlistResponse)
async def get_allowlist():
    """
    Returns the list of domains and patterns configured to bypass irrelevance.
    """
    rules = get_all_allowlist_patterns()
    return AllowlistResponse(
        rules=[AllowlistRule(**r) for r in rules],
        total=len(rules)
    )

@router.post("/api/email-triage/allowlist", response_model=AllowlistRule)
async def add_allowlist_rule(req: AllowlistCreateRequest):
    """
    Adds a new domain or email pattern to the bypass allowlist.
    """
    pat = req.pattern.strip().lower().lstrip("@")
    if not pat:
        raise HTTPException(status_code=400, detail="Pattern cannot be empty")
    
    now_iso = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        try:
            cur = conn.execute(
                "INSERT INTO email_triage_allowlist (pattern, note, created_at) VALUES (?, ?, ?)",
                (pat, req.note.strip() if req.note else "", now_iso)
            )
            rule_id = int(cur.lastrowid or 0)
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail=f"Pattern '{pat}' already exists in allowlist")
            
    return AllowlistRule(id=rule_id, pattern=pat, note=req.note, created_at=now_iso)

@router.delete("/api/email-triage/allowlist/{rule_id}")
async def delete_allowlist_rule(rule_id: int):
    """
    Removes a domain/pattern from the bypass allowlist.
    """
    with get_db_connection() as conn:
        cur = conn.execute("DELETE FROM email_triage_allowlist WHERE id = ?", (rule_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Allowlist rule not found")
        conn.commit()
    return {"success": True, "deleted_id": rule_id}

# ---------------------------------------------------------------------------
# HTML Dashboard UI View
# ---------------------------------------------------------------------------
@router.get("/email-triage", response_class=HTMLResponse)
@router.get("/triage", response_class=HTMLResponse)
@router.get("/emails", response_class=HTMLResponse)
async def get_email_triage_dashboard():
    """
    Serves the modern, interactive email triage dashboard.
    """
    if HTML_INDEX_PATH.exists() and HTML_INDEX_PATH.is_file():
        return HTMLResponse(content=HTML_INDEX_PATH.read_text(encoding="utf-8"))
    return HTMLResponse(content=FALLBACK_HTML)

# Fallback UI if static file is absent
FALLBACK_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Email Triage Engine</title>
</head>
<body style="background:#0a0f1d; color:#fff; font-family:sans-serif; padding:2rem;">
  <h2>Email Triage Dashboard</h2>
  <p>Static UI loading failed. Please check /static/email-triage/index.html</p>
</body>
</html>
"""
