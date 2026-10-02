"""Tests for homepage hub + push/share asset uploads (ppt/img/pdf etc)."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

cron_system_dir = Path(__file__).parent.parent
if str(cron_system_dir) not in sys.path:
    sys.path.insert(0, str(cron_system_dir))

import main  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)

# Use a known admin secret for upload tests (module reads env at import).
main.ADMIN_SECRET = "test-secret"
HEADERS = {"X-Admin-Secret": "test-secret"}


@pytest.fixture(autouse=True)
def _clean_uploads():
    yield
    upload_dir = cron_system_dir / "static" / "uploads"
    for f in upload_dir.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            # Only remove dummy test payloads, never real content.
            try:
                if (f.stat().st_size <= 64 and b"dummy" in f.read_bytes()) or f.name in {
                    "deck.ppt", "deck.pptx", "doc.doc", "doc.docx",
                    "sheet.xls", "sheet.xlsx", "data.csv", "notes.txt",
                    "archive.zip", "photo.avif", "photo.bmp", "audio.mp3",
                    "slides.pdf", "photo.png", "page.html", "passwd.txt",
                    "a.txt",
                }:
                    f.unlink()
            except OSError:
                pass


def _upload(filename: str, content: bytes = b"dummy-content"):
    return client.post(
        "/admin/upload",
        files={"file": (filename, content)},
        headers=HEADERS,
    )


class TestShareableExtensions:
    @pytest.mark.parametrize(
        "filename",
        [
            "deck.ppt",
            "deck.pptx",
            "doc.doc",
            "doc.docx",
            "sheet.xls",
            "sheet.xlsx",
            "data.csv",
            "notes.txt",
            "archive.zip",
            "photo.avif",
            "photo.bmp",
            "audio.mp3",
        ],
    )
    def test_office_and_asset_types_are_accepted(self, filename):
        """Push/share assets (ppt/img/pdf etc) must upload with a shareable URL."""
        res = _upload(filename)
        assert res.status_code == 200, f"{filename} rejected: {res.text}"
        data = res.json()
        assert data["url"].startswith("/uploads/")
        assert data["filename"]

    @pytest.mark.parametrize("filename", ["slides.pdf", "photo.png", "page.html"])
    def test_existing_types_still_work(self, filename):
        res = _upload(filename)
        assert res.status_code == 200
        assert res.json()["url"].startswith("/uploads/")

    def test_executable_still_rejected(self):
        res = _upload("run.exe")
        assert res.status_code == 400


class TestUploadSafety:
    def test_path_traversal_cannot_escape_uploads(self):
        res = _upload("../../etc/passwd.txt")
        # Either rejected or sanitized — must never expose outside /uploads/.
        if res.status_code == 200:
            assert res.json()["url"].startswith("/uploads/")
            assert ".." not in res.json()["url"]
            assert ".." not in res.json()["filename"]
        else:
            assert res.status_code in (400, 422)

    def test_upload_requires_admin_secret(self):
        res = client.post("/admin/upload", files={"file": ("a.txt", b"hi")})
        assert res.status_code == 401

    def test_special_char_filename_gets_encoded_url(self):
        res = _upload("report#1.pdf")
        assert res.status_code == 200
        url = res.json()["url"]
        assert "%23" in url, f"URL not encoded: {url}"
        assert "?" not in url.split("/uploads/")[-1]
        # Encoded URL must actually serve the file.
        got = client.get(url)
        assert got.status_code == 200

    def test_same_second_duplicate_uploads_stay_unique(self):
        first = _upload("dup.pptx", b"dummy-one")
        second = _upload("dup.pptx", b"dummy-two")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["url"] != second.json()["url"]
        assert client.get(first.json()["url"]).status_code == 200
        assert client.get(second.json()["url"]).status_code == 200

    def test_status_lists_newest_first_with_mtime(self):
        _upload("old-file.txt", b"dummy-old")
        _upload("new-file.txt", b"dummy-new")
        res = client.get("/admin/static/uploads/status")
        assert res.status_code == 200
        files = res.json()["files"]
        assert files
        assert all("mtime" in f for f in files)
        mtimes = [f["mtime"] for f in files]
        assert mtimes == sorted(mtimes, reverse=True)


class TestHomepageHub:
    def test_homepage_has_search(self):
        res = client.get("/")
        assert res.status_code == 200
        body = res.text
        assert 'type="search"' in body or "search" in body.lower()

    def test_homepage_has_copy_share_action(self):
        res = client.get("/")
        assert res.status_code == 200
        body = res.text.lower()
        assert "copy" in body

    def test_homepage_lists_recent_or_files(self):
        res = client.get("/")
        assert res.status_code == 200
        body = res.text.lower()
        assert "recent" in body or "files" in body

    def test_homepage_hint_mentions_office_types(self):
        res = client.get("/")
        assert res.status_code == 200
        body = res.text
        assert "PPT" in body or "ppt" in body.lower()
