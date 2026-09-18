import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure cron-system root is in sys.path
cron_system_dir = Path(__file__).parent.parent
if str(cron_system_dir) not in sys.path:
    sys.path.insert(0, str(cron_system_dir))

from wayfinder import (
    WayfinderTicket,
    WayfinderMapSummary,
    WayfinderResponse,
    RateLimitStatus,
    WayfinderService,
    parse_wayfinder_body,
)
from main import app

client = TestClient(app)

SAMPLE_MARKDOWN = """
## Destination
Build a production-grade notification dispatch service for AI-OS.

### Notes
Needs to support both Discord and Telegram webhooks with retry backoff.
Latency must stay below 200ms.

## Decisions-so-far
- Chose httpx for asynchronous requests
- Store failure logs in SQLite
- Use token bucket algorithm for rate limiting

## Tickets
- [ ] #101 Setup webhook data models (wayfinder:task)
- [x] #102 Implement Telegram bot client
- [ ] parth5012/cron-system#103 Discord dispatcher
- [ ] https://github.com/parth5012/AI-OS/issues/104 Add retry mechanism
- Plain bullet without issue reference
"""

SAMPLE_GITHUB_SEARCH_RESPONSE = {
    "total_count": 1,
    "incomplete_results": False,
    "items": [
        {
            "id": 99901,
            "number": 42,
            "title": "Map: Notification Dispatcher",
            "state": "open",
            "html_url": "https://github.com/parth5012/AI-OS/issues/42",
            "repository_url": "https://api.github.com/repos/parth5012/AI-OS",
            "body": SAMPLE_MARKDOWN,
            "labels": [{"name": "wayfinder:map"}],
            "created_at": "2026-09-01T10:00:00Z",
            "updated_at": "2026-09-02T12:00:00Z",
        }
    ]
}


class TestMarkdownParser:
    def test_parse_destination(self):
        parsed = parse_wayfinder_body(SAMPLE_MARKDOWN)
        assert "production-grade notification dispatch service" in parsed["destination"]

    def test_parse_notes(self):
        parsed = parse_wayfinder_body(SAMPLE_MARKDOWN)
        assert "Discord and Telegram webhooks" in parsed["notes"]
        assert "below 200ms" in parsed["notes"]

    def test_parse_decisions(self):
        parsed = parse_wayfinder_body(SAMPLE_MARKDOWN)
        assert len(parsed["decisions_so_far"]) == 3
        assert any("httpx" in d for d in parsed["decisions_so_far"])
        assert any("SQLite" in d for d in parsed["decisions_so_far"])

    def test_parse_child_tickets(self):
        parsed = parse_wayfinder_body(SAMPLE_MARKDOWN)
        tickets = parsed["child_tickets"]
        assert len(tickets) >= 4

        # #101: open, has slug
        t101 = next(t for t in tickets if t.number == 101)
        assert t101.is_completed is False
        assert t101.state == "open"
        assert t101.slug == "wayfinder:task"

        # #102: completed
        t102 = next(t for t in tickets if t.number == 102)
        assert t102.is_completed is True
        assert t102.state == "closed"

        # #103: repo slug
        t103 = next(t for t in tickets if t.number == 103)
        assert t103.number == 103

        # #104: full url
        t104 = next(t for t in tickets if t.number == 104)
        assert t104.number == 104
        assert t104.url == "https://github.com/parth5012/AI-OS/issues/104"

    def test_parse_empty_body(self):
        parsed = parse_wayfinder_body("")
        assert parsed["destination"] is None
        assert parsed["notes"] is None
        assert parsed["decisions_so_far"] == []
        assert parsed["child_tickets"] == []


class TestPydanticModels:
    def test_ticket_model(self):
        ticket = WayfinderTicket(
            number=123,
            title="Implement DB",
            url="https://github.com/parth5012/AI-OS/issues/123",
            state="open",
            is_completed=False,
            slug="wayfinder:task",
        )
        assert ticket.number == 123
        assert ticket.is_completed is False
        d = ticket.model_dump()
        assert d["number"] == 123

    def test_map_summary_model(self):
        summary = WayfinderMapSummary(
            id=1,
            number=42,
            title="Test Map",
            repo="parth5012/AI-OS",
            state="open",
            html_url="https://github.com/parth5012/AI-OS/issues/42",
            destination="Build AI-OS",
            notes="Some notes",
            decisions_so_far=["Decision 1"],
            child_tickets=[],
            labels=["wayfinder:map"],
        )
        assert summary.repo == "parth5012/AI-OS"
        assert summary.destination == "Build AI-OS"
        d = summary.model_dump()
        assert d["number"] == 42

    def test_response_model(self):
        resp = WayfinderResponse(
            maps=[],
            total_maps=0,
            rate_limit=RateLimitStatus(limit=60, remaining=59, reset_at=1234567890),
            cached=False,
            timestamp="2026-09-18T00:00:00Z",
        )
        assert resp.total_maps == 0
        assert resp.rate_limit.remaining == 59


class TestWayfinderServiceAndEndpoints:
    @pytest.mark.asyncio
    async def test_service_fetch_and_cache(self, monkeypatch):
        service = WayfinderService(cache_ttl=300)

        # Mock httpx response
        import httpx

        headers = {
            "x-ratelimit-limit": "60",
            "x-ratelimit-remaining": "55",
            "x-ratelimit-reset": "1700000000",
        }

        async def mock_get(self_client, url, *args, **kwargs):
            return httpx.Response(
                200,
                json=SAMPLE_GITHUB_SEARCH_RESPONSE,
                headers=headers,
                request=httpx.Request("GET", str(url)),
            )

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        # 1. Fetch data
        data1 = await service.get_maps(refresh=False)
        assert data1.total_maps == 1
        assert data1.maps[0].number == 42
        assert data1.cached is False
        assert data1.rate_limit.remaining == 55

        # 2. Fetch again -> Should be cached
        data2 = await service.get_maps(refresh=False)
        assert data2.cached is True
        assert data2.total_maps == 1

        # 3. Fetch with refresh=True -> Should bypass cache
        data3 = await service.get_maps(refresh=True)
        assert data3.cached is False

    @pytest.mark.asyncio
    async def test_service_search_rate_limited_fallback(self, monkeypatch):
        service = WayfinderService(cache_ttl=1)
        import httpx

        # Search rate limited (403)
        async def mock_get(self_client, url, *args, **kwargs):
            if "search/issues" in str(url):
                return httpx.Response(
                    403,
                    json={"message": "API rate limit exceeded"},
                    headers={
                        "x-ratelimit-limit": "10",
                        "x-ratelimit-remaining": "0",
                        "x-ratelimit-reset": "1700000000",
                    },
                    request=httpx.Request("GET", str(url)),
                )
            # Repo fallback
            return httpx.Response(
                200,
                json=SAMPLE_GITHUB_SEARCH_RESPONSE["items"],
                headers={
                    "x-ratelimit-limit": "60",
                    "x-ratelimit-remaining": "40",
                    "x-ratelimit-reset": "1700000000",
                },
                request=httpx.Request("GET", str(url)),
            )

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        data = await service.get_maps(refresh=True)
        assert data.total_maps >= 1
        assert data.maps[0].number == 42

    def test_api_wayfinder_endpoint(self, monkeypatch):
        import httpx

        headers = {
            "x-ratelimit-limit": "60",
            "x-ratelimit-remaining": "50",
            "x-ratelimit-reset": "1700000000",
        }

        async def mock_get(self, url, *args, **kwargs):
            return httpx.Response(
                200,
                json=SAMPLE_GITHUB_SEARCH_RESPONSE,
                headers=headers,
                request=httpx.Request("GET", url),
            )

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)

        # GET /api/wayfinder
        res = client.get("/api/wayfinder?refresh=true")
        assert res.status_code == 200
        body = res.json()
        assert "maps" in body
        assert body["total_maps"] == 1
        assert body["maps"][0]["number"] == 42
        assert "production-grade notification dispatch" in body["maps"][0]["destination"]

    def test_wayfinder_html_fallback(self):
        res = client.get("/wayfinder")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "<html" in res.text.lower()
        assert "wayfinder" in res.text.lower()

    def test_wayfinder_html_custom_file(self, tmp_path, monkeypatch):
        custom_html = "<!DOCTYPE html><html><body>Custom Wayfinder UI</body></html>"
        custom_file = tmp_path / "index.html"
        custom_file.write_text(custom_html, encoding="utf-8")

        monkeypatch.setattr("wayfinder.WAYFINDER_HTML_PATH", custom_file)

        res = client.get("/wayfinder")
        assert res.status_code == 200
        assert "Custom Wayfinder UI" in res.text
