import html
import os
import shutil
from urllib.parse import quote
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from cron_engine import get_engine
from antigravity import router as antigravity_router
from pull_requests import router as pull_requests_router
from wayfinder import router as wayfinder_router
from email_triage import router as email_triage_router
from homepage import render_homepage

# ---------------------------------------------------------------------------
# Constants & Config
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / 'static'


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path.lower()
        if path.endswith('/sw.js') or path == '/sw.js':
            response.headers['Cache-Control'] = 'no-cache, no-store'
        elif path.endswith('/') or 'index.html' in path:
            response.headers['Cache-Control'] = 'no-cache'
        elif any(
            path.endswith(ext)
            for ext in [
                '.html', '.css', '.js', '.png', '.jpg', '.jpeg',
                '.gif', '.webp', '.avif', '.bmp', '.tif', '.tiff',
                '.mp3', '.wav', '.ogg', '.mp4', '.webm', '.mov',
                '.pdf', '.svg', '.ppt', '.pptx', '.doc', '.docx',
                '.xls', '.xlsx', '.csv', '.txt', '.md', '.json', '.zip',
            ]
        ):
            response.headers['Cache-Control'] = 'public, max-age=86400'
        return response

app = FastAPI(title="Cron System", version="1.0.0")


ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')
ALLOWED_EXTENSIONS = {
    # documents / slides / sheets / data (push & share assets)
    '.html', '.pdf', '.ppt', '.pptx', '.doc', '.docx',
    '.xls', '.xlsx', '.csv', '.txt', '.md', '.json', '.zip',
    # images
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif', '.bmp',
    '.tif', '.tiff', '.svg', '.ico',
    # audio / video
    '.mp3', '.wav', '.ogg', '.mp4', '.webm', '.mov',
}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

def verify_admin(x_admin_secret: str = Header(None)):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail='Invalid admin secret')

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(CacheControlMiddleware)




@app.get("/health")
async def health():
    return {"status": "ok"}




@app.get('/admin/static')
async def list_static():
    if not STATIC_DIR.exists():
        return []
    results = []
    for sub in sorted(STATIC_DIR.iterdir()):
        if sub.is_dir():
            files = list(sub.rglob('*'))
            file_list = [f for f in files if f.is_file()]
            total_bytes = sum(f.stat().st_size for f in file_list)
            results.append({
                'slug': sub.name,
                'file_count': len(file_list),
                'total_bytes': total_bytes,
                'mounted_at': f'/{sub.name}'
            })
    return results

@app.get('/admin/static/{slug}/status')
async def static_status(slug: str):
    target = STATIC_DIR / slug
    if not target.exists() or not target.is_dir():
        raise HTTPException(status_code=404, detail=f'Static content not found: {slug}')
    files = [f for f in target.rglob('*') if f.is_file()]
    # Newest-first so "recent uploads" actually shows recent work, not alpha order.
    files_sorted = sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)
    return {
        'slug': slug,
        'file_count': len(files_sorted),
        'total_bytes': sum(f.stat().st_size for f in files_sorted),
        'files': [
            {'name': str(f.relative_to(target)), 'size': f.stat().st_size, 'mtime': f.stat().st_mtime}
            for f in files_sorted
        ],
        'mounted_at': f'/{slug}'
    }

@app.delete('/admin/static/{slug}')
async def delete_static(slug: str, x_admin_secret: str = Header(None)):
    verify_admin(x_admin_secret)
    target = STATIC_DIR / slug
    if not target.exists():
        raise HTTPException(status_code=404, detail=f'Not found: {slug}')
    shutil.rmtree(target)
    return {'deleted': slug, 'status': 'ok'}


@app.post('/admin/upload')
async def upload_file(
    file: UploadFile = File(...),  # noqa: B008
    x_admin_secret: str = Header(None),
):
    verify_admin(x_admin_secret)

    safe_name = Path(file.filename or '').name.strip()
    if not safe_name or safe_name in {'.', '..'}:
        raise HTTPException(status_code=400, detail='Invalid filename')

    ext = Path(safe_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f'File type {ext} not allowed')

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        max_mb = MAX_UPLOAD_SIZE // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f'File too large. Max {max_mb}MB')

    upload_dir = STATIC_DIR / 'uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)

    dest = upload_dir / safe_name
    # Belt-and-braces: never allow escape from uploads dir.
    try:
        dest.resolve().relative_to(upload_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail='Invalid filename') from None
    # Allocate a unique destination atomically-ish: re-check after each
    # timestamp-suffixed proposal so a same-second batch cannot overwrite.
    if dest.exists():
        base_stem = Path(safe_name).stem
        counter = 0
        while dest.exists():
            counter += 1
            ts = int(datetime.now(timezone.utc).timestamp())
            dest = upload_dir / f'{base_stem}_{ts}_{counter}{ext}'

    dest.write_bytes(content)
    return {'url': f'/uploads/{quote(dest.name)}', 'size': len(content), 'filename': dest.name}

@app.get('/', response_class=HTMLResponse)
async def index():
    return render_homepage(STATIC_DIR)


# Include Wayfinder & Pull Requests routers
app.include_router(wayfinder_router)
app.include_router(pull_requests_router)
app.include_router(antigravity_router)
app.include_router(email_triage_router)


# ---------------------------------------------------------------------------
# PWA Routes (Manifest & Service Worker)
# ---------------------------------------------------------------------------
@app.get('/pwa/manifest.webmanifest')
async def pwa_manifest():
    manifest_path = STATIC_DIR / 'pwa' / 'manifest.webmanifest'
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail='Manifest not found')
    return FileResponse(manifest_path, media_type='application/manifest+json')


@app.get('/pwa/sw.js')
async def pwa_sw():
    sw_path = STATIC_DIR / 'pwa' / 'sw.js'
    if not sw_path.exists():
        raise HTTPException(status_code=404, detail='Service worker not found')
    return FileResponse(
        sw_path,
        media_type='application/javascript',
        headers={'Cache-Control': 'no-cache, no-store'},
    )


# ---------------------------------------------------------------------------
# Cron System APIs
# ---------------------------------------------------------------------------
@app.get('/api/jobs')
async def list_jobs():
    engine = get_engine()
    return [
        {
            'name': job.name,
            'schedule': job.schedule,
            'description': job.description,
            'timeout_sec': job.timeout_sec,
        }
        for job in engine.jobs.values()
    ]


@app.get('/api/cron/{name}/logs')
async def get_cron_logs(name: str, limit: int = 50):
    engine = get_engine()
    if not engine.is_valid_job(name):
        raise HTTPException(status_code=404, detail=f'Job not found: {name}')
    logs = engine.get_logs(name, limit=limit)
    return [asdict(r) for r in logs]


def mount_static_dirs(app):
    if not STATIC_DIR.exists():
        return
    # These directories are served by their own routers (self-contained HTML),
    # so they must not also be mounted as raw static file trees.
    router_owned = {"wayfinder", "pull-requests", "email-triage", "antigravity"}
    for sub in sorted(STATIC_DIR.iterdir()):
        if sub.is_dir():
            if sub.name in router_owned:
                continue
            app.mount(
                f"/{sub.name}",
                StaticFiles(directory=str(sub), html=True),
                name=f"static-{sub.name}",
            )
            for child in sorted(sub.iterdir()):
                if child.is_dir():
                    app.mount(
                        f"/{sub.name}/{child.name}",
                        StaticFiles(directory=str(child), html=True),
                        name=f"static-{sub.name}-{child.name}",
                    )


mount_static_dirs(app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
