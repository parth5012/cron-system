"""Tests for Antigravity quota classifier (Batch 1: pure functions)."""

import sys
from pathlib import Path

# Ensure cron-system root is in sys.path
cron_system_dir = Path(__file__).parent.parent
if str(cron_system_dir) not in sys.path:
    sys.path.insert(0, str(cron_system_dir))

from antigravity import (  # noqa: E402
    AntigravityService,
    bucket_for_family,
    classify_family,
    is_exhausted,
    is_token_expired,
    load_accounts_from_env,
    load_token_file,
    parse_quota_entry,
    refresh_access_token,
    summarize_family,
)


def test_classify_family_gemini():
    assert classify_family("gemini-3-pro") == "gemini"
    assert classify_family("gemini-3.5-flash-high") == "gemini"


def test_classify_family_claude():
    assert classify_family("claude-sonnet-4-5") == "claude"
    assert classify_family("claude-opus-4-7") == "claude"


def test_classify_family_openai():
    assert classify_family("gpt-oss-120b-medium") == "openai"


def test_bucket_for_family():
    assert bucket_for_family("gemini")["primary"] == "weekly"
    assert bucket_for_family("claude")["primary"] == "5h"
    assert bucket_for_family("openai")["primary"] == "5h"


def test_parse_quota_entry_normalizes():
    entry = parse_quota_entry(
        "gemini-3-pro",
        {"remainingFraction": 0.9, "resetTime": "2026-10-08T00:00:00Z"},
    )
    assert entry["family"] == "gemini"
    assert entry["window"] == "weekly"
    assert entry["remaining"] == 0.9


def test_parse_quota_entry_claude_window():
    entry = parse_quota_entry(
        "claude-sonnet-4-5",
        {"remainingFraction": 0.12, "resetTime": "2026-10-03T16:00:00Z"},
    )
    assert entry["family"] == "claude"
    assert entry["window"] == "5h"


def test_parse_quota_entry_invalid_returns_none():
    assert parse_quota_entry("", {}) is None
    assert parse_quota_entry("gemini-3-pro", {}) is None


def test_is_exhausted_threshold():
    assert is_exhausted(0.04) is True
    assert is_exhausted(0.05) is False
    assert is_exhausted(0.9) is False


def test_summarize_family_picks_minimum():
    entries = [
        {"family": "gemini", "remaining": 0.9, "resetTime": "2026-10-08T00:00:00Z"},
        {"family": "gemini", "remaining": 0.4, "resetTime": "2026-10-09T00:00:00Z"},
    ]
    summary = summarize_family("gemini", entries)
    assert summary["remaining"] == 0.4
    assert summary["exhausted"] is False


# ---------------------------------------------------------------------------
# Batch 2: service + accounts registry (mocked httpx)
# ---------------------------------------------------------------------------
import json  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402

import antigravity  # noqa: E402

FETCH_MODELS_PAYLOAD = {
    "models": {
        "gemini-3-pro": {
            "quotaInfo": {"remainingFraction": 0.9, "resetTime": "2026-10-08T00:00:00Z"}
        },
        "claude-sonnet-4-5": {
            "quotaInfo": {"remainingFraction": 0.12, "resetTime": "2026-10-03T16:00:00Z"}
        },
    }
}


def _env_accounts(monkeypatch):
    payload = json.dumps(
        [
            {"id": "acc-1@gmail.com", "projectId": "project-alpha", "access_token": "ya29.test1"},
            {"id": "acc-2@gmail.com", "projectId": "project-beta", "access_token": "ya29.test2"},
        ]
    )
    monkeypatch.setenv("ANTIGRAVITY_ACCOUNTS_JSON", payload)


def make_fetch_mock(calls=None, status: int = 200, payload=None):
    body = FETCH_MODELS_PAYLOAD if payload is None else payload

    async def mock_post(self_client, url, *args, **kwargs):
        if calls is not None:
            calls.append(str(url))
        return httpx.Response(
            status,
            json=body if status == 200 else {"error": "boom"},
            request=httpx.Request("POST", str(url)),
        )

    return mock_post


@pytest.fixture()
def svc(monkeypatch):
    _env_accounts(monkeypatch)
    service = AntigravityService(cache_ttl=180.0)
    monkeypatch.setattr(antigravity, "_antigravity_service", service)
    return service


def test_load_accounts_from_env(monkeypatch):
    _env_accounts(monkeypatch)
    accounts = load_accounts_from_env()
    assert [a["id"] for a in accounts] == ["acc-1@gmail.com", "acc-2@gmail.com"]
    assert accounts[0]["projectId"] == "project-alpha"


def test_load_accounts_empty(monkeypatch):
    monkeypatch.delenv("ANTIGRAVITY_ACCOUNTS_JSON", raising=False)
    assert load_accounts_from_env() == []


@pytest.mark.asyncio
async def test_snapshot_splits_families(monkeypatch, svc):
    monkeypatch.setattr(httpx.AsyncClient, "post", make_fetch_mock())
    snap = await svc.get_snapshot(refresh=True)
    assert snap.cached is False
    assert len(snap.accounts) == 2
    first = snap.accounts[0]
    by_family = {f.family: f for f in first.families}
    assert by_family["gemini"].window == "weekly"
    assert by_family["claude"].window == "5h"
    assert by_family["gemini"].remaining == 0.9
    assert by_family["claude"].remaining == 0.12


@pytest.mark.asyncio
async def test_snapshot_cache_hit_no_http(monkeypatch, svc):
    calls: list = []
    monkeypatch.setattr(httpx.AsyncClient, "post", make_fetch_mock(calls=calls))
    await svc.get_snapshot(refresh=True)
    calls.clear()
    second = await svc.get_snapshot(refresh=False)
    assert second.cached is True
    assert calls == []


@pytest.mark.asyncio
async def test_snapshot_error_does_not_raise(monkeypatch, svc):
    monkeypatch.setattr(httpx.AsyncClient, "post", make_fetch_mock(status=429))
    snap = await svc.get_snapshot(refresh=True)
    assert snap.error is not None
    assert len(snap.accounts) == 2


# ---------------------------------------------------------------------------
# Batch 3: router + OmniRoute preview/sync + HTML
# ---------------------------------------------------------------------------
from fastapi.testclient import TestClient  # noqa: E402

from antigravity import build_omniroute_limits  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(autouse=True)
def _mock_upstream(monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, "post", make_fetch_mock())


def test_limits_endpoint_contract(monkeypatch):
    _env_accounts(monkeypatch)
    response = client.get("/api/antigravity/limits?refresh=true")
    assert response.status_code == 200
    body = response.json()
    assert "accounts" in body and "timestamp" in body
    assert len(body["accounts"]) == 2
    families = {f["family"] for a in body["accounts"] for f in a["families"]}
    assert {"gemini", "claude"} <= families


def test_omniroute_preview_has_weekly_rows(monkeypatch):
    _env_accounts(monkeypatch)
    response = client.get("/api/antigravity/omniroute-preview")
    assert response.status_code == 200
    rows = response.json()["limits"]
    windows = {r["resetInterval"] for r in rows}
    assert "weekly" in windows
    assert all(r["scopeValue"] == "antigravity" for r in rows)


def test_build_omniroute_limits_pure():
    snap = AntigravityService(cache_ttl=0.0)
    assert snap is not None
    assert build_omniroute_limits is not None


def test_sync_disabled_by_default(monkeypatch):
    _env_accounts(monkeypatch)
    response = client.post("/api/antigravity/sync")
    assert response.status_code == 200
    assert response.json()["synced"] == 0


def test_dashboard_html_served():
    response = client.get("/antigravity")
    assert response.status_code == 200
    assert "Antigravity Limits" in response.text
    assert "/api/antigravity/limits" in response.text


# ---------------------------------------------------------------------------
# Batch 4: persistent auth (refresh_token auto-renewal, token-file source)
# ---------------------------------------------------------------------------
from datetime import datetime, timedelta, timezone  # noqa: E402

from antigravity import OAUTH_TOKEN_URL  # noqa: E402

FAKE_FILE_TOKENS = {
    "token": {
        "access_token": "ya29.file-access",
        "token_type": "Bearer",
        "refresh_token": "1//file-refresh",
        "expiry": "2099-01-01T00:00:00+00:00",
    },
    "auth_method": "oauth2",
}


def _write_token_file(tmp_path, payload=None):
    target = tmp_path / "antigravity-oauth-token"
    target.write_text(json.dumps(FAKE_FILE_TOKENS if payload is None else payload))
    return str(target)


def test_is_token_expired():
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    assert is_token_expired(past) is True
    assert is_token_expired(future) is False
    assert is_token_expired("") is True
    assert is_token_expired("not-a-date") is True
    assert is_token_expired(None) is True


def test_load_token_file(tmp_path):
    path = _write_token_file(tmp_path)
    tokens = load_token_file(path)
    assert tokens is not None
    assert tokens["access_token"] == "ya29.file-access"
    assert tokens["refresh_token"] == "1//file-refresh"
    assert tokens["expiry"] == "2099-01-01T00:00:00+00:00"


def test_load_token_file_missing(tmp_path):
    assert load_token_file(str(tmp_path / "nope.json")) is None
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    assert load_token_file(str(broken)) is None


@pytest.mark.asyncio
async def test_refresh_access_token(monkeypatch):
    async def mock_post(self_client, url, *args, **kwargs):
        assert str(url) == OAUTH_TOKEN_URL
        assert kwargs.get("data", {}).get("grant_type") == "refresh_token"
        return httpx.Response(
            200,
            json={"access_token": "ya29.renewed", "expires_in": 3600},
            request=httpx.Request("POST", str(url)),
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    async with httpx.AsyncClient() as http:
        renewed = await refresh_access_token(http, "1//r", "cid", "csecret")
    assert renewed is not None
    assert renewed["access_token"] == "ya29.renewed"


@pytest.mark.asyncio
async def test_refresh_access_token_failure(monkeypatch):
    async def mock_post(self_client, url, *args, **kwargs):
        return httpx.Response(
            400, json={"error": "invalid_grant"}, request=httpx.Request("POST", str(url))
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    async with httpx.AsyncClient() as http:
        assert await refresh_access_token(http, "bad", "cid", "csecret") is None


def make_auth_mock(calls=None, fetch_statuses=None, token_payload=None):
    statuses = list(fetch_statuses or [200])
    body = dict(token_payload or {"access_token": "ya29.renewed", "expires_in": 3600})

    async def mock_post(self_client, url, *args, **kwargs):
        target = str(url)
        if calls is not None:
            calls.append(target)
        if "oauth2.googleapis.com/token" in target:
            return httpx.Response(200, json=body, request=httpx.Request("POST", target))
        status = statuses.pop(0) if len(statuses) > 1 else statuses[0]
        if status != 200:
            return httpx.Response(status, json={"error": "unauthorized"}, request=httpx.Request("POST", target))
        return httpx.Response(200, json=FETCH_MODELS_PAYLOAD, request=httpx.Request("POST", target))

    return mock_post


@pytest.mark.asyncio
async def test_service_auto_refresh_on_401(monkeypatch):
    monkeypatch.setenv(
        "ANTIGRAVITY_ACCOUNTS_JSON",
        json.dumps(
            [
                {
                    "id": "acc-1@gmail.com",
                    "projectId": "project-alpha",
                    "access_token": "ya29.stale",
                    "refresh_token": "1//refresh-me",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                }
            ]
        ),
    )
    calls: list = []
    monkeypatch.setattr(
        httpx.AsyncClient, "post", make_auth_mock(calls=calls, fetch_statuses=[401, 200])
    )
    service = AntigravityService(cache_ttl=180.0)
    snap = await service.get_snapshot(refresh=True)
    assert snap.error is None
    assert len(snap.accounts) == 1
    assert not snap.accounts[0].error
    assert any("oauth2.googleapis.com/token" in c for c in calls)
    by_family = {f.family: f for f in snap.accounts[0].families}
    assert by_family["gemini"].remaining == 0.9


@pytest.mark.asyncio
async def test_service_401_without_refresh_creds_reports_error(monkeypatch):
    monkeypatch.setenv(
        "ANTIGRAVITY_ACCOUNTS_JSON",
        json.dumps(
            [{"id": "acc-1@gmail.com", "projectId": "p", "access_token": "ya29.stale"}]
        ),
    )
    monkeypatch.delenv("ANTIGRAVITY_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("ANTIGRAVITY_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.setattr(httpx.AsyncClient, "post", make_auth_mock(fetch_statuses=[401]))
    service = AntigravityService(cache_ttl=180.0)
    snap = await service.get_snapshot(refresh=True)
    assert snap.error is not None
    assert snap.accounts[0].error is not None


@pytest.mark.asyncio
async def test_service_stores_rotated_refresh_token(monkeypatch):
    monkeypatch.setenv(
        "ANTIGRAVITY_ACCOUNTS_JSON",
        json.dumps(
            [
                {
                    "id": "acc-1@gmail.com",
                    "projectId": "project-alpha",
                    "access_token": "ya29.stale",
                    "refresh_token": "1//old-refresh",
                    "client_id": "test-client-id",
                }
            ]
        ),
    )
    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        make_auth_mock(
            fetch_statuses=[401, 200],
            token_payload={
                "access_token": "ya29.renewed",
                "expires_in": 3600,
                "refresh_token": "1//rotated-refresh",
            },
        ),
    )
    service = AntigravityService(cache_ttl=180.0)
    snap = await service.get_snapshot(refresh=True)
    assert snap.error is None
    assert service._live_refresh.get("acc-1@gmail.com") == "1//rotated-refresh"


@pytest.mark.asyncio
async def test_service_bootstraps_from_refresh_token_only(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTIGRAVITY_TOKEN_FILE", str(tmp_path / "no-token-file"))
    monkeypatch.setenv(
        "ANTIGRAVITY_ACCOUNTS_JSON",
        json.dumps(
            [
                {
                    "id": "acc-1@gmail.com",
                    "projectId": "",
                    "refresh_token": "1//only-refresh",
                    "client_id": "test-client-id",
                    "client_secret": "test-client-secret",
                }
            ]
        ),
    )
    calls: list = []
    monkeypatch.setattr(
        httpx.AsyncClient, "post", make_auth_mock(calls=calls, fetch_statuses=[200])
    )
    service = AntigravityService(cache_ttl=180.0)
    snap = await service.get_snapshot(refresh=True)
    assert snap.error is None
    assert not snap.accounts[0].error
    assert any("oauth2.googleapis.com/token" in c for c in calls)
    by_family = {f.family: f for f in snap.accounts[0].families}
    assert by_family["gemini"].remaining == 0.9


@pytest.mark.asyncio
async def test_service_reads_token_file(monkeypatch, tmp_path):
    path = _write_token_file(tmp_path)
    monkeypatch.setenv(
        "ANTIGRAVITY_ACCOUNTS_JSON",
        json.dumps([{"id": "acc-1@gmail.com", "projectId": "p", "token_file": path}]),
    )
    seen: dict = {}

    async def mock_post(self_client, url, *args, **kwargs):
        seen["auth"] = (kwargs.get("headers") or {}).get("Authorization")
        return httpx.Response(200, json=FETCH_MODELS_PAYLOAD, request=httpx.Request("POST", str(url)))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post)
    service = AntigravityService(cache_ttl=180.0)
    snap = await service.get_snapshot(refresh=True)
    assert snap.error is None
    assert seen.get("auth") == "Bearer ya29.file-access"
