import sys
from pathlib import Path

from fastapi.testclient import TestClient

# Ensure cron-system root is in sys.path
cron_system_dir = Path(__file__).parent.parent
if str(cron_system_dir) not in sys.path:
    sys.path.insert(0, str(cron_system_dir))

from main import app  # noqa: E402

client = TestClient(app)


class TestPwaEndpoints:
    def test_pwa_index_html(self):
        """GET /pwa/ serves the PWA app shell with 200 and text/html."""
        res = client.get("/pwa/")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")

    def test_pwa_manifest_media_type(self):
        """GET /pwa/manifest.webmanifest serves with application/manifest+json."""
        res = client.get("/pwa/manifest.webmanifest")
        assert res.status_code == 200
        assert "application/manifest+json" in res.headers.get("content-type", "")
        data = res.json()
        assert "name" in data
        assert "icons" in data

    def test_pwa_service_worker_headers(self):
        """GET /pwa/sw.js serves with no-cache, no-store and javascript media type."""
        res = client.get("/pwa/sw.js")
        assert res.status_code == 200
        content_type = res.headers.get("content-type", "")
        assert "javascript" in content_type
        cache_control = res.headers.get("cache-control", "")
        assert "no-cache" in cache_control
        assert "no-store" in cache_control

    def test_pwa_shell_has_pr_tab_and_bottom_nav(self):
        """The app shell exposes the PR tab and a mobile bottom navigation."""
        res = client.get("/pwa/")
        assert res.status_code == 200
        body = res.text
        assert 'data-tab="prs"' in body, "PR tab missing from the shell"
        assert 'id="tab-prs"' in body, "PR tab pane missing from the shell"
        assert 'id="prList"' in body, "PR list container missing from the shell"
        assert 'class="bottom-nav"' in body, "mobile bottom nav missing"
        # safe-area inset is what keeps the bar clear of the iOS home indicator
        assert "env(safe-area-inset-bottom" in body
        # 16px inputs prevent mobile browser zoom-on-focus
        assert "font-size: 16px" in body

    def test_pull_requests_page_ships(self):
        """The standalone PR dashboard is mounted and self-contained."""
        res = client.get("/pull-requests")
        assert res.status_code == 200
        assert "text/html" in res.headers.get("content-type", "")
        assert "/api/pull-requests" in res.text
        assert "env(safe-area-inset-bottom" in res.text


class TestApiJobsAndLogs:
    def test_get_api_jobs(self):
        """GET /api/jobs returns list of configured jobs without secrets."""
        res = client.get("/api/jobs")
        assert res.status_code == 200
        jobs = res.json()
        assert isinstance(jobs, list)
        assert len(jobs) >= 3

        job_names = [j["name"] for j in jobs]
        assert "warmup" in job_names
        assert "freelance-ingest" in job_names
        assert "backup" in job_names

        for job in jobs:
            assert "name" in job
            assert "schedule" in job
            assert "description" in job
            assert "timeout_sec" in job
            # Secret must NOT be leaked
            assert "secret" not in job

    def test_get_api_cron_logs_valid_job(self):
        """GET /api/cron/{name}/logs returns list of logs for known job."""
        res = client.get("/api/cron/warmup/logs?limit=50")
        assert res.status_code == 200
        logs = res.json()
        assert isinstance(logs, list)

    def test_get_api_cron_logs_unknown_job(self):
        """GET /api/cron/{name}/logs returns 404 for unknown job."""
        res = client.get("/api/cron/nonexistent_xyz/logs")
        assert res.status_code == 404
        assert "not found" in res.json().get("detail", "").lower()


class TestExistingMountsUnbroken:
    def test_health_check(self):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json() == {"status": "ok"}

    def test_wayfinder_unbroken(self):
        res = client.get("/wayfinder")
        assert res.status_code == 200

    def test_admin_static_unbroken(self):
        res = client.get("/admin/static")
        assert res.status_code == 200
