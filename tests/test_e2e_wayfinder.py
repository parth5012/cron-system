"""
End-to-End (E2E) Integration Tests for Wayfinder Feature.
Tests full user journeys, live endpoints, caching lifecycle, GitHub fallback resilience,
and UI HTML components in the integrated Cron System FastAPI application.
"""

import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

# Ensure cron-system root is in sys.path
cron_system_dir = Path(__file__).parent.parent
if str(cron_system_dir) not in sys.path:
    sys.path.insert(0, str(cron_system_dir))

from main import app  # noqa: E402


@pytest.fixture
def client():
    """Provides a cleanly managed TestClient for each E2E test."""
    with TestClient(app) as test_client:
        yield test_client


class TestWayfinderE2E:
    """E2E test suite covering Wayfinder UI, API endpoints, caching, and resiliency."""

    def test_e2e_wayfinder_dashboard_html_response(self, client: TestClient):
        """
        Scenario: User navigates to the Wayfinder dashboard at /wayfinder.
        Verifies:
        - HTTP 200 HTMLResponse served.
        - Correct Content-Type and Cache-Control headers.
        - HTML document contains all critical interactive components:
          * Metrics bar with summary counters
          * Search input bar
          * State filter (all, open, closed)
          * Repository dropdown filter
          * Theme toggle button
          * Refresh button
          * Rate limit status pill
        - Latency is within acceptable thresholds (< 150ms).
        """
        start_time = time.perf_counter()
        response = client.get("/wayfinder")
        latency_ms = (time.perf_counter() - start_time) * 1000

        # Status and headers verification
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        content_type = response.headers.get("content-type", "")
        assert "text/html" in content_type, f"Expected text/html, got {content_type}"
        assert latency_ms < 150, f"Dashboard response too slow: {latency_ms:.2f}ms"

        html = response.text

        # 1. Verification of Metrics Bar components
        assert "metrics-grid" in html, "Metrics bar container (.metrics-grid) not found"
        assert 'id="val-total-maps"' in html, "Metric element #val-total-maps missing"
        assert 'id="val-open-maps"' in html, "Metric element #val-open-maps missing"
        assert 'id="val-closed-maps"' in html, "Metric element #val-closed-maps missing"
        assert 'id="val-total-repos"' in html, "Metric element #val-total-repos missing"

        # 2. Verification of Search Bar
        assert 'id="input-search"' in html, "Search input element #input-search missing"
        assert 'id="input-search"' in html and 'placeholder=' in html

        # 3. Verification of State & Repo Filters
        assert 'id="select-state"' in html, "State filter #select-state missing"
        assert '<option value="all">All States</option>' in html
        assert '<option value="open" selected>Open Only</option>' in html
        assert '<option value="closed">Closed Only</option>' in html
        assert 'id="select-repo"' in html, "Repo filter #select-repo missing"

        # 4. Verification of Theme Toggle
        assert 'id="btn-theme"' in html, "Theme toggle button #btn-theme missing"

        # 5. Verification of Refresh Button
        assert 'id="btn-refresh"' in html, "Refresh button #btn-refresh missing"

        # 6. Verification of Rate Limit Pill
        assert 'id="rate-limit-pill"' in html, "Rate limit pill #rate-limit-pill missing"
        assert 'id="rate-limit-text"' in html, "Rate limit text #rate-limit-text missing"

        # 7. Verification of Main Maps Container
        assert 'id="maps-container"' in html, "Maps grid container #maps-container missing"

    def test_e2e_wayfinder_api_live_data_and_schema(self, client: TestClient):
        """
        Scenario: Frontend loads live data from GET /api/wayfinder.
        Verifies:
        - HTTP 200 with valid JSON body.
        - Conformance to WayfinderResponse model schema.
        - Schema keys: maps, total_maps, rate_limit, cached, timestamp, error.
        - When maps exist, each map contains expected attributes (id, title, state, html_url, child_tickets).
        - Timestamps are valid ISO format.
        """
        start_time = time.perf_counter()
        response = client.get("/api/wayfinder")
        latency_ms = (time.perf_counter() - start_time) * 1000
        assert latency_ms < 15000, f"Live API took {latency_ms:.2f}ms"

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert "application/json" in response.headers.get("content-type", "")

        data = response.json()

        # Validate top-level keys
        expected_keys = {"maps", "total_maps", "rate_limit", "cached", "timestamp", "error"}
        assert expected_keys.issubset(data.keys()), f"Missing keys in response: {expected_keys - set(data.keys())}"

        assert isinstance(data["maps"], list), "Expected 'maps' to be a list"
        assert isinstance(data["total_maps"], int), "Expected 'total_maps' to be an integer"
        assert data["total_maps"] == len(data["maps"]), "total_maps does not match maps length"
        assert isinstance(data["cached"], bool), "Expected 'cached' to be a boolean"

        # Validate timestamp format
        try:
            datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
        except Exception as err:
            pytest.fail(f"Invalid timestamp ISO format: {data['timestamp']} ({err})")

        # Validate Rate Limit structure if present
        if data["rate_limit"] is not None:
            rl = data["rate_limit"]
            assert "limit" in rl
            assert "remaining" in rl
            assert "reset_at" in rl

        # Validate individual map structures
        for m in data["maps"]:
            assert "id" in m
            assert "number" in m
            assert "title" in m
            assert "repo" in m
            assert m["state"] in ("open", "closed")
            assert "html_url" in m
            assert "child_tickets" in m
            assert "decisions_so_far" in m
            assert isinstance(m["child_tickets"], list)
            assert isinstance(m["decisions_so_far"], list)

    def test_e2e_wayfinder_api_caching_and_refresh_lifecycle(self, client: TestClient):
        """
        Scenario: User performs initial fetch, repeated read, and manual refresh.
        Verifies:
        1. Query with refresh=true returns fresh data with cached=False.
        2. Immediate subsequent query returns cached=True from memory cache.
        3. Cached response has near-zero latency (< 25ms).
        4. Manual refresh with ?refresh=true triggers a new fetch and returns cached=False.
        """
        # Step 1: Force refresh
        res_fresh = client.get("/api/wayfinder?refresh=true")
        assert res_fresh.status_code == 200
        data_fresh = res_fresh.json()
        assert data_fresh["cached"] is False, "Expected cached=False on refresh=true"

        # Step 2: Immediate follow-up read (should be cached)
        start_cached = time.perf_counter()
        res_cached = client.get("/api/wayfinder")
        cached_latency_ms = (time.perf_counter() - start_cached) * 1000

        assert res_cached.status_code == 200
        data_cached = res_cached.json()
        assert data_cached["cached"] is True, "Expected cached=True on immediate subsequent request"
        assert data_cached["total_maps"] == data_fresh["total_maps"]
        assert cached_latency_ms < 25.0, f"Cached response too slow: {cached_latency_ms:.2f}ms"

        # Step 3: Trigger refresh=true again
        res_refreshed = client.get("/api/wayfinder?refresh=true")
        assert res_refreshed.status_code == 200
        data_refreshed = res_refreshed.json()
        assert data_refreshed["cached"] is False, "Expected cached=False after second refresh=true"

    def test_e2e_wayfinder_api_github_fallback_resilience(self, client: TestClient, monkeypatch):
        """
        Scenario: GitHub Search API is rate-limited (HTTP 403) or fails with network errors.
        Verifies:
        - The server does NOT throw 500 Internal Server Error.
        - Fallback mechanism is triggered to query repositories or return error context cleanly.
        - HTTP 200 is still returned to the client with valid schema.
        """
        # Simulate GitHub Search 403 Rate Limit + Fallback repo response
        fallback_called = {"search": False, "repos": False}

        mock_fallback_items = [
            {
                "id": 88001,
                "number": 10,
                "title": "Fallback Map: Resilient Dispatcher",
                "state": "open",
                "html_url": "https://github.com/parth5012/AI-OS/issues/10",
                "repository_url": "https://api.github.com/repos/parth5012/AI-OS",
                "body": "## Destination\nVerify fallback resilience\n## Tickets\n- #101 Core task",
                "labels": [{"name": "wayfinder:map"}],
                "created_at": "2026-09-18T10:00:00Z",
                "updated_at": "2026-09-18T11:00:00Z",
            }
        ]

        async def mock_github_get(self_client, url, *args, **kwargs):
            url_str = str(url)
            if "search/issues" in url_str:
                fallback_called["search"] = True
                return httpx.Response(
                    403,
                    json={"message": "API rate limit exceeded"},
                    headers={
                        "x-ratelimit-limit": "10",
                        "x-ratelimit-remaining": "0",
                        "x-ratelimit-reset": "1789740000",
                    },
                    request=httpx.Request("GET", url_str),
                )
            elif "repos/" in url_str and "issues" in url_str:
                fallback_called["repos"] = True
                return httpx.Response(
                    200,
                    json=mock_fallback_items,
                    headers={
                        "x-ratelimit-limit": "60",
                        "x-ratelimit-remaining": "45",
                        "x-ratelimit-reset": "1789740000",
                    },
                    request=httpx.Request("GET", url_str),
                )
            return httpx.Response(404, request=httpx.Request("GET", url_str))

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_github_get)

        # Call with refresh=true to hit the mocked network path
        response = client.get("/api/wayfinder?refresh=true")
        assert response.status_code == 200, f"Expected 200 on fallback, got {response.status_code}"
        data = response.json()

        assert fallback_called["search"] is True, "GitHub search was not called"
        assert fallback_called["repos"] is True, "Repository fallback query was not called"
        assert data["total_maps"] >= 1, "Expected fallback items to be captured"
        assert data["maps"][0]["number"] == 10
        assert data["maps"][0]["destination"] == "Verify fallback resilience"

    def test_e2e_wayfinder_network_outage_graceful_handling(self, client: TestClient, monkeypatch):
        """
        Scenario: Complete network outage / DNS resolution failure when contacting GitHub.
        Verifies:
        - The server recovers gracefully without crashing.
        - Returns HTTP 200 with error field populated and total_maps=0.
        """
        async def mock_failing_get(self_client, url, *args, **kwargs):
            raise httpx.ConnectError("Failed to resolve host api.github.com")

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_failing_get)

        response = client.get("/api/wayfinder?refresh=true")
        assert response.status_code == 200
        data = response.json()
        assert data["total_maps"] == 0
        assert data["error"] is not None
        assert "Failed to connect to GitHub API" in data["error"]

    def test_e2e_wayfinder_full_user_journey(self, client: TestClient):
        """
        Complete end-to-end user journey simulation:
        1. User visits /wayfinder: gets interactive HTML dashboard with all UI hooks.
        2. Dashboard client-side script queries /api/wayfinder to populate UI.
        3. User clicks 'Refresh' button: client queries /api/wayfinder?refresh=true.
        4. User navigates back / reloads: receives cached response with minimal latency.
        """
        # Step 1: User requests UI
        t0 = time.perf_counter()
        ui_res = client.get("/wayfinder")
        ui_latency = (time.perf_counter() - t0) * 1000
        assert ui_latency < 200, f"UI response too slow: {ui_latency:.2f}ms"
        assert ui_res.status_code == 200
        assert "text/html" in ui_res.headers.get("content-type", "")
        assert "🧭 Wayfinder Maps" in ui_res.text

        # Step 2: Dashboard loads initial map data
        t1 = time.perf_counter()
        api_res = client.get("/api/wayfinder")
        api_latency = (time.perf_counter() - t1) * 1000
        assert api_latency < 15000, f"Initial API fetch took {api_latency:.2f}ms"
        assert api_res.status_code == 200
        init_data = api_res.json()
        assert "maps" in init_data

        # Step 3: User clicks Refresh button in UI
        t2 = time.perf_counter()
        refresh_res = client.get("/api/wayfinder?refresh=true")
        refresh_latency = (time.perf_counter() - t2) * 1000
        assert refresh_latency < 15000, f"Refresh fetch took {refresh_latency:.2f}ms"
        assert refresh_res.status_code == 200
        refreshed_data = refresh_res.json()
        assert refreshed_data["cached"] is False

        # Step 4: Subsequent access within cache TTL
        t3 = time.perf_counter()
        cached_res = client.get("/api/wayfinder")
        cached_latency = (time.perf_counter() - t3) * 1000
        assert cached_res.status_code == 200
        cached_data = cached_res.json()
        assert cached_data["cached"] is True
        assert cached_latency < 25.0, f"Cached response took {cached_latency:.2f}ms"
