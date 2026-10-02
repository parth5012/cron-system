"""Tests for the GitHub Pull Requests module, API endpoints and HTML view."""

import sys
from pathlib import Path
from typing import Any, List, Optional

import httpx
import pytest
from fastapi.testclient import TestClient

# Ensure cron-system root is in sys.path
cron_system_dir = Path(__file__).parent.parent
if str(cron_system_dir) not in sys.path:
    sys.path.insert(0, str(cron_system_dir))

import pull_requests  # noqa: E402
from main import app  # noqa: E402
from pull_requests import (  # noqa: E402
    PullRequest,
    PullRequestService,
    PullRequestsResponse,
    build_search_queries,
    extract_repo_slug,
)

client = TestClient(app)

OWNER = "parth5012"

SEARCH_ITEM = {
    "id": 9001,
    "number": 7,
    "title": "feat: ship pull requests module",
    "state": "open",
    "html_url": "https://github.com/parth5012/cron-system/pull/7",
    "repository_url": "https://api.github.com/repos/parth5012/cron-system",
    "user": {"login": OWNER},
    "created_at": "2026-09-01T10:00:00Z",
    "updated_at": "2026-09-20T10:00:00Z",
    "comments": 3,
    "labels": [{"name": "enhancement"}, {"name": "pwa"}],
    "draft": False,
    "pull_request": {
        "url": "https://api.github.com/repos/parth5012/cron-system/pulls/7",
        "html_url": "https://github.com/parth5012/cron-system/pull/7",
    },
}

SEARCH_ITEM_REVIEW = {
    "id": 9002,
    "number": 12,
    "title": "fix: tighten pwa safe area insets",
    "state": "open",
    "html_url": "https://github.com/parth5012/Vela/pull/12",
    "repository_url": "https://api.github.com/repos/parth5012/Vela",
    "user": {"login": "contributor-one"},
    "created_at": "2026-09-05T10:00:00Z",
    "updated_at": "2026-09-21T10:00:00Z",
    "comments": 1,
    "labels": [],
    "draft": True,
    "pull_request": {
        "url": "https://api.github.com/repos/parth5012/Vela/pulls/12",
        "html_url": "https://github.com/parth5012/Vela/pull/12",
    },
}

REPO_PULL_ITEM = {
    "id": 9003,
    "number": 21,
    "title": "chore: bump deps",
    "state": "open",
    "html_url": "https://github.com/parth5012/AI-OS/pull/21",
    "user": {"login": OWNER},
    "created_at": "2026-09-02T10:00:00Z",
    "updated_at": "2026-09-19T10:00:00Z",
    "comments": 0,
    "labels": [{"name": "deps"}],
    "draft": False,
    "head": {"ref": "feature/bump-deps"},
    "base": {"ref": "main"},
}

DETAIL_ITEM = {
    "id": 9001,
    "number": 7,
    "additions": 120,
    "deletions": 34,
    "changed_files": 9,
    "draft": False,
    "html_url": SEARCH_ITEM["html_url"],
    "user": {"login": OWNER},
    "head": {"ref": "feature/pr-module"},
    "base": {"ref": "main"},
}

RATE_HEADERS = {
    "x-ratelimit-limit": "30",
    "x-ratelimit-remaining": "27",
    "x-ratelimit-reset": "1700000000",
}


@pytest.fixture(autouse=True)
def fresh_service(monkeypatch):
    """Isolate every test from the module-level cache singleton."""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    service = PullRequestService(cache_ttl=120.0)
    monkeypatch.setattr(pull_requests, "_pull_request_service", service)
    return service


def make_github_mock(
    search_status: int = 200,
    search_items: Optional[List[dict]] = None,
    repo_pulls: Optional[List[dict]] = None,
    detail: Any = "__default__",
    raise_on_search: bool = False,
    calls: list = None,
):
    """Build a monkeypatchable httpx.AsyncClient.get replacement."""
    search_items = [SEARCH_ITEM, SEARCH_ITEM_REVIEW] if search_items is None else search_items
    repo_pulls = [REPO_PULL_ITEM] if repo_pulls is None else repo_pulls
    detail = DETAIL_ITEM if detail == "__default__" else detail

    def _record(url, kwargs):
        if calls is not None:
            calls.append((str(url), kwargs.get("params") or {}))

    async def mock_get(self_client, url, *args, **kwargs):
        target = str(url)
        _record(url, kwargs)

        if "search/issues" in target:
            if raise_on_search:
                raise httpx.ConnectError("connection refused")
            if search_status != 200:
                return httpx.Response(
                    search_status,
                    json={"message": "API rate limit exceeded"},
                    headers={"x-ratelimit-limit": "10", "x-ratelimit-remaining": "0"},
                    request=httpx.Request("GET", target),
                )
            query = (kwargs.get("params") or {}).get("q", "")
            items = search_items
            if "author:" in query:
                items = [i for i in search_items if i["user"]["login"] == OWNER]
            else:
                items = [i for i in search_items if i["user"]["login"] != OWNER]
            return httpx.Response(
                200,
                json={"total_count": len(items), "items": items},
                headers=RATE_HEADERS,
                request=httpx.Request("GET", target),
            )

        if target.endswith("/pulls"):
            return httpx.Response(
                200,
                json=repo_pulls,
                headers=RATE_HEADERS,
                request=httpx.Request("GET", target),
            )

        if "/pulls/" in target:
            if detail is None:
                return httpx.Response(
                    404,
                    json={"message": "Not Found"},
                    request=httpx.Request("GET", target),
                )
            return httpx.Response(
                200,
                json=detail,
                headers=RATE_HEADERS,
                request=httpx.Request("GET", target),
            )

        return httpx.Response(
            404,
            json={"message": "Not Found"},
            request=httpx.Request("GET", target),
        )

    return mock_get


class TestPullRequestModel:
    def test_pull_request_defaults(self):
        pr = PullRequest(id=1, number=2, title="t", repo=f"{OWNER}/r", html_url="u")
        assert pr.draft is False
        assert pr.additions == 0
        assert pr.deletions == 0
        assert pr.comments_count == 0
        assert pr.labels == []
        assert pr.role == "author"
        assert pr.branch_head is None

    def test_response_payload_contract(self):
        payload = PullRequestsResponse(
            prs=[PullRequest(id=1, number=2, title="t", repo=f"{OWNER}/r", html_url="u")],
            total_count=1,
            rate_limit_remaining=27,
            timestamp="2026-09-20T10:00:00+00:00",
        ).model_dump()
        for key in ("prs", "total_count", "cached", "rate_limit_remaining"):
            assert key in payload
        assert isinstance(payload["rate_limit_remaining"], int)


class TestSearchQueryBuilder:
    def test_author_query_exact(self):
        queries = build_search_queries(involved=False)
        assert queries == [f"type:pr state:open author:{OWNER}"]

    def test_involved_adds_reviewer_and_assignee(self):
        queries = build_search_queries(involved=True)
        assert queries[0] == f"type:pr state:open author:{OWNER}"
        assert f"type:pr state:open review-requested:{OWNER}" in queries
        assert f"type:pr state:open assignee:{OWNER}" in queries


class TestRepoSlugExtraction:
    def test_from_repository_url(self):
        assert extract_repo_slug(SEARCH_ITEM) == f"{OWNER}/cron-system"

    def test_from_html_url(self):
        item = {
            "html_url": "https://github.com/parth5012/Vela/pull/12",
        }
        assert extract_repo_slug(item) == f"{OWNER}/Vela"

    def test_unknown_fallback(self):
        assert extract_repo_slug({}) == f"{OWNER}/unknown"


class TestServiceCacheLifecycle:
    @pytest.mark.asyncio
    async def test_miss_then_hit_then_refresh(self, monkeypatch, fresh_service):
        calls: list = []
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock(calls=calls))

        first = await fresh_service.get_pull_requests(refresh=False)
        assert first.cached is False
        assert first.total_count >= 1
        search_calls = len([c for c in calls if "search/issues" in c[0]])
        assert search_calls > 0

        calls.clear()
        second = await fresh_service.get_pull_requests(refresh=False)
        assert second.cached is True
        assert second.total_count == first.total_count
        assert calls == [], "cache hit must not hit the GitHub API"

        calls.clear()
        third = await fresh_service.get_pull_requests(refresh=True)
        assert third.cached is False
        assert len([c for c in calls if "search/issues" in c[0]]) > 0

    @pytest.mark.asyncio
    async def test_cache_expiry_triggers_refetch(self, monkeypatch, fresh_service):
        calls: list = []
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock(calls=calls))
        fresh_service.cache_ttl = 0.0

        await fresh_service.get_pull_requests(refresh=True)
        calls.clear()
        again = await fresh_service.get_pull_requests(refresh=False)
        assert again.cached is False
        assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_cache_isolated_per_involved_flag(self, monkeypatch, fresh_service):
        calls: list = []
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock(calls=calls))

        authored = await fresh_service.get_pull_requests(refresh=True, involved=False)
        assert [pr.repo for pr in authored.prs] == [f"{OWNER}/cron-system", f"{OWNER}/AI-OS"]

        involved = await fresh_service.get_pull_requests(refresh=True, involved=True)
        repos = {pr.repo for pr in involved.prs}
        assert f"{OWNER}/Vela" in repos, "reviewer/assignee PRs must be unioned in"

        calls.clear()
        again = await fresh_service.get_pull_requests(refresh=False, involved=True)
        assert again.cached is True
        assert calls == []

    @pytest.mark.asyncio
    async def test_parses_all_required_fields(self, monkeypatch, fresh_service):
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock())
        data = await fresh_service.get_pull_requests(refresh=True, involved=False)
        pr = next(p for p in data.prs if p.number == 7)
        assert pr.id == 9001
        assert pr.repo == f"{OWNER}/cron-system"
        assert pr.author == OWNER
        assert pr.html_url == SEARCH_ITEM["html_url"]
        assert pr.comments_count == 3
        assert pr.labels == ["enhancement", "pwa"]
        assert pr.created_at == "2026-09-01T10:00:00Z"
        assert pr.updated_at == "2026-09-20T10:00:00Z"
        # enriched from the single-PR endpoint
        assert pr.additions == 120
        assert pr.deletions == 34
        assert pr.branch_head == "feature/pr-module"
        assert pr.branch_base == "main"
        assert pr.role == "author"

    @pytest.mark.asyncio
    async def test_search_and_repo_listing_are_deduplicated(self, monkeypatch, fresh_service):
        """
        GitHub's search API returns the *issue* id for a PR while the pulls
        listing returns the *pull request* id, so the         same PR arrives with two different ids. It must still be listed exactly
        once, and the branch data only present on the listing must survive.
        """
        # Simulate the cross-id collision: search yields #7 as an issue id,
        # the repo listing yields the same PR as a pull id.
        async def mock_get(self_client, url, *args, **kwargs):
            target = str(url)
            if "search/issues" in target:
                query = (kwargs.get("params") or {}).get("q", "")
                if "author:" in query:
                    return httpx.Response(
                        200,
                        json={
                            "total_count": 1,
                            "items": [dict(SEARCH_ITEM, repository_url="https://api.github.com/repos/parth5012/cron-system")],
                        },
                        headers=RATE_HEADERS,
                        request=httpx.Request("GET", target),
                    )
                return httpx.Response(
                    200,
                    json={"total_count": 0, "items": []},
                    headers=RATE_HEADERS,
                    request=httpx.Request("GET", target),
                )
            if target.endswith("/pulls"):
                return httpx.Response(
                    200,
                    # same PR (cron-system#7) but reported with a pull id
                    json=[
                        {
                            "id": 4242,
                            "number": 7,
                            "title": SEARCH_ITEM["title"],
                            "state": "open",
                            "html_url": SEARCH_ITEM["html_url"],
                            "user": {"login": OWNER},
                            "created_at": SEARCH_ITEM["created_at"],
                            "updated_at": SEARCH_ITEM["updated_at"],
                            "comments": 3,
                            "labels": [{"name": "enhancement"}, {"name": "pwa"}],
                            "draft": False,
                            "head": {"ref": "feature/pr-module"},
                            "base": {"ref": "main"},
                        }
                    ],
                    headers=RATE_HEADERS,
                    request=httpx.Request("GET", target),
                )
            return httpx.Response(
                404,
                json={"message": "Not Found"},
                request=httpx.Request("GET", target),
            )

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        data = await fresh_service.get_pull_requests(refresh=True, involved=False)
        numbers = [pr.number for pr in data.prs]
        assert numbers.count(7) == 1, f"PR #7 duplicated across sources: {numbers}"
        assert len(numbers) == len(set(numbers)), f"duplicate PRs in payload: {numbers}"
        pr = data.prs[0]
        # Branch data only exists on the pulls listing — merging must keep it
        assert pr.branch_head == "feature/pr-module"
        assert pr.branch_base == "main"
        assert pr.role == "author"
        assert pr.labels == ["enhancement", "pwa"]

    @pytest.mark.asyncio
    async def test_repo_listing_does_not_mask_reviewer_role(self, monkeypatch, fresh_service):
        """
        A PR matched by the review-requested search must keep its reviewer role
        even when the repo listing returns the same PR under a different id.
        """

        async def mock_get(self_client, url, *args, **kwargs):
            target = str(url)
            if "search/issues" in target:
                query = (kwargs.get("params") or {}).get("q", "")
                items = [SEARCH_ITEM_REVIEW] if "review-requested:" in query else []
                return httpx.Response(
                    200,
                    json={"total_count": len(items), "items": items},
                    headers=RATE_HEADERS,
                    request=httpx.Request("GET", target),
                )
            if target.endswith("/pulls"):
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": 7777,  # different id, same PR
                            "number": 12,
                            "title": SEARCH_ITEM_REVIEW["title"],
                            "state": "open",
                            "html_url": SEARCH_ITEM_REVIEW["html_url"],
                            "user": {"login": "contributor-one"},
                            "updated_at": SEARCH_ITEM_REVIEW["updated_at"],
                            "comments": 1,
                            "labels": [],
                            "draft": True,
                            "head": {"ref": "fix/safe-area"},
                            "base": {"ref": "main"},
                        }
                    ],
                    headers=RATE_HEADERS,
                    request=httpx.Request("GET", target),
                )
            return httpx.Response(
                404, json={"message": "Not Found"}, request=httpx.Request("GET", target)
            )

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        data = await fresh_service.get_pull_requests(refresh=True, involved=True)
        pr = next(p for p in data.prs if p.number == 12)
        assert pr.role == "reviewer"
        assert pr.review_requested is True
        assert pr.branch_head == "fix/safe-area"

    @pytest.mark.asyncio
    async def test_repo_fallback_provides_branch_and_draft(self, monkeypatch, fresh_service):
        # detail=None disables the single-PR enrichment endpoint
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock(detail=None))
        data = await fresh_service.get_pull_requests(refresh=True, involved=False)
        pr = next(p for p in data.prs if p.number == 21)
        assert pr.branch_head == "feature/bump-deps"
        assert pr.branch_base == "main"


class TestServiceResilience:
    @pytest.mark.asyncio
    async def test_rate_limited_search_falls_back_to_repos(self, monkeypatch, fresh_service):
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock(search_status=403))
        data = await fresh_service.get_pull_requests(refresh=True, involved=False)
        assert data.total_count >= 1, "per-repo fallback should recover data"
        assert {pr.repo for pr in data.prs} == {f"{OWNER}/AI-OS"}
        # The degradation is still reported so the UI can explain itself.
        assert data.error and "rate limited" in data.error.lower()
        assert data.rate_limit_remaining == 0

    @pytest.mark.asyncio
    async def test_network_error_returns_graceful_payload(self, monkeypatch, fresh_service):
        async def mock_get(self_client, url, *args, **kwargs):
            raise httpx.ConnectError("network down")

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        data = await fresh_service.get_pull_requests(refresh=True)
        assert data.prs == []
        assert data.total_count == 0
        assert data.error
        assert "network down" in data.error

    @pytest.mark.asyncio
    async def test_non_pr_search_items_are_ignored(self, monkeypatch, fresh_service):
        issue_item = {
            "id": 777,
            "number": 99,
            "title": "plain issue, not a PR",
            "html_url": "https://github.com/parth5012/cron-system/issues/99",
            "repository_url": "https://api.github.com/repos/parth5012/cron-system",
            "user": {"login": OWNER},
            "updated_at": "2026-09-22T10:00:00Z",
            "labels": [],
        }
        monkeypatch.setattr(
            httpx.AsyncClient,
            "get",
            make_github_mock(search_items=[issue_item], repo_pulls=[]),
        )
        data = await fresh_service.get_pull_requests(refresh=True, involved=False)
        assert [pr.number for pr in data.prs] == []

    @pytest.mark.asyncio
    async def test_token_enables_authenticated_mode(self, monkeypatch, fresh_service):
        monkeypatch.setenv("GH_TOKEN", '  "ghp_faketoken"  ')
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock())
        data = await fresh_service.get_pull_requests(refresh=True)
        assert data.authenticated is True
        assert data.error is None

    @pytest.mark.asyncio
    async def test_unauthenticated_reports_public_mode(self, monkeypatch, fresh_service):
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock())
        data = await fresh_service.get_pull_requests(refresh=True)
        assert data.authenticated is False


class TestPartialSearchFailure:
    @pytest.mark.asyncio
    async def test_partial_search_failure_still_reported(self, monkeypatch, fresh_service):
        """
        Author query succeeds, reviewer query 403s: the author PRs are still
        returned, but the degradation must stay visible because reviewer/assignee
        PRs outside GITHUB_REPOS were never searched.
        """

        async def mock_get(self_client, url, *args, **kwargs):
            target = str(url)
            if "search/issues" in target:
                query = (kwargs.get("params") or {}).get("q", "")
                if "author:" in query:
                    return httpx.Response(
                        200,
                        json={"total_count": 1, "items": [SEARCH_ITEM]},
                        headers=RATE_HEADERS,
                        request=httpx.Request("GET", target),
                    )
                return httpx.Response(
                    403,
                    json={"message": "API rate limit exceeded"},
                    headers={"x-ratelimit-limit": "10", "x-ratelimit-remaining": "0"},
                    request=httpx.Request("GET", target),
                )
            if target.endswith("/pulls"):
                return httpx.Response(
                    200,
                    json=[REPO_PULL_ITEM],
                    headers=RATE_HEADERS,
                    request=httpx.Request("GET", target),
                )
            return httpx.Response(
                404, json={"message": "Not Found"}, request=httpx.Request("GET", target)
            )

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        data = await fresh_service.get_pull_requests(refresh=True, involved=True)
        assert sorted(pr.number for pr in data.prs) == [7, 21]
        assert data.error and "rate limited" in data.error.lower(), (
            "a failed reviewer/assignee query must not be silently cleared by "
            "successful repo listings"
        )

    @pytest.mark.asyncio
    async def test_rate_limit_reports_most_constrained_budget(self, monkeypatch, fresh_service):
        """
        Search (10/min) and core (60/hr) share the x-ratelimit-remaining header.
        The reported number must be the most constrained reading, not the last.
        """

        async def mock_get(self_client, url, *args, **kwargs):
            target = str(url)
            if "search/issues" in target:
                return httpx.Response(
                    200,
                    json={"total_count": 1, "items": [SEARCH_ITEM]},
                    headers={"x-ratelimit-limit": "10", "x-ratelimit-remaining": "2"},
                    request=httpx.Request("GET", target),
                )
            if target.endswith("/pulls"):
                return httpx.Response(
                    200,
                    json=[],
                    headers={"x-ratelimit-limit": "60", "x-ratelimit-remaining": "57"},
                    request=httpx.Request("GET", target),
                )
            return httpx.Response(
                404, json={"message": "Not Found"}, request=httpx.Request("GET", target)
            )

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        data = await fresh_service.get_pull_requests(refresh=True, involved=False)
        assert data.rate_limit_remaining == 2, "must report the most constrained budget"
        assert data.rate_limit.remaining == 2


class TestApiEndpoint:
    def test_api_pull_requests_cache_lifecycle(self, monkeypatch):
        calls: list = []
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock(calls=calls))

        res = client.get("/api/pull-requests?involved=false")
        assert res.status_code == 200
        body = res.json()
        assert set(["prs", "total_count", "cached", "rate_limit_remaining"]).issubset(body)
        assert body["cached"] is False
        assert body["total_count"] >= 1
        assert isinstance(body["rate_limit_remaining"], int)
        first_numbers = sorted(p["number"] for p in body["prs"])

        calls.clear()
        res2 = client.get("/api/pull-requests?involved=false")
        assert res2.json()["cached"] is True
        assert sorted(p["number"] for p in res2.json()["prs"]) == first_numbers
        assert calls == [], "second request must be served from the in-memory cache"

        res3 = client.get("/api/pull-requests?involved=false&refresh=true")
        assert res3.json()["cached"] is False
        assert len([c for c in calls if "search/issues" in c[0]]) > 0

    def test_api_pull_requests_rate_limited_is_graceful(self, monkeypatch):
        monkeypatch.setattr(httpx.AsyncClient, "get", make_github_mock(search_status=403))
        res = client.get("/api/pull-requests?refresh=true&involved=false")
        assert res.status_code == 200
        body = res.json()
        assert "prs" in body
        assert body["rate_limit_remaining"] == 0

    def test_api_pull_requests_network_error_is_graceful(self, monkeypatch):
        async def mock_get(self_client, url, *args, **kwargs):
            raise httpx.ConnectError("connection reset by peer")

        monkeypatch.setattr(httpx.AsyncClient, "get", mock_get)
        res = client.get("/api/pull-requests?refresh=true")
        assert res.status_code == 200
        body = res.json()
        assert body["prs"] == []
        assert body["total_count"] == 0
        assert "connection reset by peer" in body["error"]


class TestPullRequestHtmlView:
    def test_serves_standalone_html(self):
        res = client.get("/pull-requests")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "<html" in res.text.lower()
        assert "pull" in res.text.lower()

    def test_serves_custom_file(self, tmp_path, monkeypatch):
        custom = tmp_path / "index.html"
        custom.write_text(
            "<!DOCTYPE html><html><body>Custom PR dashboard</body></html>",
            encoding="utf-8",
        )
        monkeypatch.setattr(pull_requests, "PULL_REQUESTS_HTML_PATH", custom)
        res = client.get("/pull-requests")
        assert res.status_code == 200
        assert "Custom PR dashboard" in res.text

    def test_fallback_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pull_requests, "PULL_REQUESTS_HTML_PATH", tmp_path / "nope.html")
        res = client.get("/pull-requests")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "pull request" in res.text.lower()
