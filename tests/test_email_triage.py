"""
Tests for Email Triage feature in cron-system.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from starlette.testclient import TestClient

cron_system_dir = Path(__file__).parent.parent
if str(cron_system_dir) not in sys.path:
    sys.path.insert(0, str(cron_system_dir))

from main import app
import email_triage

client = TestClient(app)

MOCK_ENVELOPES = [
    {
        "id": "1001",
        "subject": "Re: [parth5012/warden] feat: LangGraph checkpointing foundation (PR #1)",
        "from": [{"name": "coderabbitai[bot]", "email": "notifications@github.com"}],
        "date": "2026-10-11T04:06:34-07:00",
        "size": 45599,
        "flags": ["*"]
    },
    {
        "id": "1002",
        "subject": "50% off autumn sneaker clearance sale",
        "from": [{"name": "SneakerOutlet", "email": "deals@sneakers.com"}],
        "date": "2026-10-11T03:00:00Z",
        "size": 12000,
        "flags": []
    }
]

def test_email_triage_html_routes():
    """Verify that dashboard HTML endpoints render successfully."""
    for path in ["/email-triage", "/triage", "/emails"]:
        res = client.get(path)
        assert res.status_code == 200
        assert "text/html" in res.headers["content-type"]
        assert "Email Triage Engine" in res.text
        assert "TypeSafe Jev System One" in res.text

def test_api_list_emails_mocked():
    """Verify GET /api/email-triage/emails merges Himalaya envelopes with cache and allowlist."""
    with patch("email_triage.fetch_envelopes_from_himalaya", return_value=MOCK_ENVELOPES):
        res = client.get("/api/email-triage/emails?limit=2")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 2
        assert len(data["emails"]) == 2
        assert data["emails"][0]["id"] == "1001"
        assert data["emails"][0]["sender_name"] == "coderabbitai[bot]"
        assert data["emails"][0]["allowlisted"] is True, "notifications@github.com should match github.com allowlist"
        assert data["emails"][1]["id"] == "1002"
        assert data["emails"][1]["allowlisted"] is False

def test_api_categorize_mocked():
    """Verify POST /api/email-triage/categorize evaluates decision models and returns taxonomy."""
    mock_classified = {
        "message_id": "1002",
        "category": "irrelevant",
        "is_irrelevant_prob": 0.95,
        "urgency_score": 0.1,
        "action_required_prob": 0.02,
        "categorized_at": "2026-10-11T00:00:00Z"
    }
    
    with patch("email_triage.fetch_envelopes_from_himalaya", return_value=[MOCK_ENVELOPES[1]]):
        with patch("email_triage.classify_single_email", return_value=mock_classified):
            res = client.post("/api/email-triage/categorize", json={"email_ids": ["1002"], "force_refresh": True})
            assert res.status_code == 200
            data = res.json()
            assert data["categorized_count"] == 1
            assert "1002" in data["results"]
            assert data["results"]["1002"]["category"] == "irrelevant"
            assert data["results"]["1002"]["is_irrelevant_prob"] == 0.95

def test_api_archive_mocked():
    """Verify POST /api/email-triage/archive calls Himalaya message move."""
    with patch("email_triage.move_messages_to_archive", return_value={"archived": ["1002"], "errors": []}):
        res = client.post("/api/email-triage/archive", json={"message_ids": ["1002"]})
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["archived_count"] == 1
        assert data["message_ids"] == ["1002"]

def test_api_read_body_mocked():
    """Verify GET /api/email-triage/email/{id}/body returns parsed body."""
    mock_body = {
        "id": "1001",
        "subject": "PR Update",
        "sender": "bot@github.com",
        "body_text": "Here is the pull request review content.",
        "is_html": False
    }
    with patch("email_triage.extract_email_body_text", return_value=mock_body):
        res = client.get("/api/email-triage/email/1001/body")
        assert res.status_code == 200
        data = res.json()
        assert data["id"] == "1001"
        assert "pull request review" in data["body_text"]

def test_api_allowlist_crud():
    """Verify CRUD operations on allowlist rules."""
    # 1. Fetch current list (should include seeded rules)
    res = client.get("/api/email-triage/allowlist")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    existing_patterns = [r["pattern"] for r in data["rules"]]
    assert "github.com" in existing_patterns

    # 2. Add new test pattern
    test_pattern = "pytest-unit-test-domain.io"
    add_res = client.post("/api/email-triage/allowlist", json={"pattern": test_pattern, "note": "Test rule"})
    assert add_res.status_code == 200
    rule = add_res.json()
    assert rule["pattern"] == test_pattern
    rule_id = rule["id"]

    # Duplicate check
    dup_res = client.post("/api/email-triage/allowlist", json={"pattern": test_pattern, "note": "Dup"})
    assert dup_res.status_code == 409

    # 3. Delete rule
    del_res = client.delete(f"/api/email-triage/allowlist/{rule_id}")
    assert del_res.status_code == 200
    assert del_res.json()["deleted_id"] == rule_id

    # 4. Verify gone
    res_after = client.get("/api/email-triage/allowlist")
    patterns_after = [r["pattern"] for r in res_after.json()["rules"]]
    assert test_pattern not in patterns_after

@pytest.mark.asyncio
async def test_classify_clef_worker_ai_format():
    """Verify classify_single_email processes Cloudflare Workers AI Clef response correctly."""
    mock_cf_response = {
        "result": {
            "model": "clef-flash",
            "answers": {
                "is_irrelevant": {"type": "noul", "noul": 0.08},
                "category": {
                    "type": "choice",
                    "choice": "work",
                    "probabilities": {"work": 0.95, "irrelevant": 0.05}
                },
                "urgency": {"type": "score", "score": 0.45},
                "action_required": {"type": "noul", "noul": 0.25}
            }
        },
        "success": True,
        "errors": []
    }

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_cf_response
    mock_client.post = pytest.importorskip("unittest.mock").AsyncMock(return_value=mock_resp)

    res = await email_triage.classify_single_email(
        http_client=mock_client,
        email=MOCK_ENVELOPES[0],
        provider="cloudflare",
        model="@cf/cloudflare/clef-flash",
        cloudflare_token="fake-token",
        cloudflare_account_id="fake-account"
    )

    assert res["category"] == "work"
    assert res["is_irrelevant_prob"] == 0.0  # github.com is allowlisted
    assert res["urgency_score"] == 0.45
    assert res["provider"] == "cloudflare"
    assert res["model"] == "@cf/cloudflare/clef-flash"

def test_api_categorize_clef_provider_selection():
    """Verify POST /api/email-triage/categorize passes provider and model options."""
    mock_classified = {
        "message_id": "1002",
        "category": "personal",
        "is_irrelevant_prob": 0.1,
        "urgency_score": 0.5,
        "action_required_prob": 0.3,
        "categorized_at": "2026-10-11T00:00:00Z",
        "provider": "cloudflare",
        "model": "@cf/cloudflare/clef-flash"
    }

    with patch("email_triage.fetch_envelopes_from_himalaya", return_value=[MOCK_ENVELOPES[1]]):
        with patch("email_triage.classify_single_email", return_value=mock_classified) as mock_classify:
            res = client.post(
                "/api/email-triage/categorize",
                json={
                    "email_ids": ["1002"],
                    "force_refresh": True,
                    "provider": "cloudflare",
                    "model": "@cf/cloudflare/clef-flash"
                }
            )
            assert res.status_code == 200
            data = res.json()
            assert data["categorized_count"] == 1
            assert "1002" in data["results"]
            assert data["results"]["1002"]["category"] == "personal"
            # Verify classify_single_email was called with cloudflare provider
            mock_classify.assert_called_once()
            _, kwargs = mock_classify.call_args
            assert kwargs["provider"] == "cloudflare"
            assert kwargs["model"] == "@cf/cloudflare/clef-flash"
