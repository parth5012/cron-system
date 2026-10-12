import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app as fastapi_app

class VercelPathFixer:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            headers = dict(scope.get("headers", []))
            matched_path = (
                headers.get(b"x-matched-path", b"")
                or headers.get(b"x-invoke-path", b"")
                or headers.get(b"x-forwarded-uri", b"")
            ).decode("utf-8")

            curr_path = scope.get("path", "")
            if curr_path in ("/api/index.py", "/api/index", "/api"):
                scope["path"] = matched_path if matched_path else "/"
            elif matched_path and curr_path.startswith("/api/index.py"):
                scope["path"] = matched_path

        await self.app(scope, receive, send)

app = VercelPathFixer(fastapi_app)
