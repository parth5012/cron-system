import sys
from pathlib import Path
from fastapi import Request
from fastapi.responses import JSONResponse

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app as fastapi_app

@fastapi_app.exception_handler(404)
async def custom_404(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "detail": "Not Found",
            "path": request.url.path,
            "scope_path": request.scope.get("path"),
            "headers": dict(request.headers),
        },
    )

app = fastapi_app
