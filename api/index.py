import sys
from pathlib import Path
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from main import app as fastapi_app

@fastapi_app.exception_handler(StarletteHTTPException)
async def custom_http_exception(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return JSONResponse(
            status_code=404,
            content={
                "custom_debug": True,
                "url": str(request.url),
                "path": request.url.path,
                "scope_path": request.scope.get("path"),
                "headers": dict(request.headers),
            },
        )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

app = fastapi_app
