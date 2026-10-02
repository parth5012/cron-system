import html
import os
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from cron_engine import get_engine
from pull_requests import router as pull_requests_router
from wayfinder import router as wayfinder_router

# ---------------------------------------------------------------------------
# Constants & Config
# ---------------------------------------------------------------------------
STATIC_DIR = Path('static')


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
    return {
        'slug': slug,
        'file_count': len(files),
        'total_bytes': sum(f.stat().st_size for f in files),
        'files': [
            {'name': str(f.relative_to(target)), 'size': f.stat().st_size}
            for f in sorted(files)
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
    if dest.exists():
        stem = dest.stem
        dest = upload_dir / f'{stem}_{int(datetime.now(timezone.utc).timestamp())}{ext}'

    dest.write_bytes(content)
    return {'url': f'/uploads/{dest.name}', 'size': len(content), 'filename': dest.name}

@app.get('/', response_class=HTMLResponse)
async def index():
    directories = []
    total_files = 0
    total_bytes_all = 0
    if STATIC_DIR.exists():
        for sub in sorted(STATIC_DIR.iterdir()):
            if sub.is_dir():
                files = list(sub.rglob('*'))
                file_list = [f for f in files if f.is_file()]
                total_bytes = sum(f.stat().st_size for f in file_list)
                total_files += len(file_list)
                total_bytes_all += total_bytes
                size_mb = total_bytes / (1024 * 1024)
                size_kb = total_bytes / 1024
                formatted_size = (
                    f"{size_mb:.2f} MB" if total_bytes > 1024 * 1024 else f"{size_kb:.2f} KB"
                )
                directories.append({
                    'slug': sub.name,
                    'file_count': len(file_list),
                    'total_size': formatted_size,
                    'url': f'/{sub.name}',
                })

    total_mb = total_bytes_all / (1024 * 1024)
    total_label = (
        f"{total_mb:.2f} MB" if total_bytes_all > 1024 * 1024
        else f"{total_bytes_all / 1024:.2f} KB"
    )

    dirs_html = "".join([
        f"<div class='dir-card' data-slug='{html.escape(d['slug'])}'>"
        f"<h3><a href='{html.escape(d['url'])}'>{html.escape(d['slug'])}</a></h3>"
        f"<p>{d['file_count']} files • {d['total_size']}</p>"
        f"<div class='card-actions'>"
        f"<a class='btn' href='{html.escape(d['url'])}'>Open</a>"
        f"<button class='btn ghost' data-copy-url='{html.escape(d['url'])}'>Copy link</button>"
        f"</div></div>"
        for d in directories
    ]) or "<p class='empty'>No content yet — upload a file below to share it.</p>"

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
        <title>📂 Cron System - Content Hub</title>
        <link rel="icon" type="image/svg+xml" href="/icons/ghost.svg">
        <style>
            :root {{
                --bg: #f8f9fa;
                --text: #212529;
                --card-bg: #fff;
                --border: #dee2e6;
                --primary: #0d6efd;
            }}
            @media (prefers-color-scheme: dark) {{
                :root {{
                    --bg: #212529;
                    --text: #f8f9fa;
                    --card-bg: #343a40;
                    --border: #495057;
                    --primary: #4dabff;
                }}
            }}
            * {{ box-sizing: border-box; }}
            body {{
                font-family: system-ui, -apple-system, sans-serif;
                margin: 0;
                padding: 20px;
                background: var(--bg);
                color: var(--text);
            }}
            .container {{ max-width: 960px; margin: 0 auto; }}
            header.top {{
                display: flex;
                flex-wrap: wrap;
                align-items: center;
                gap: 12px;
                justify-content: space-between;
                margin-bottom: 8px;
            }}
            header.top h1 {{ margin: 0; font-size: 1.6rem; }}
            nav.links {{ display: flex; gap: 8px; flex-wrap: wrap; }}
            nav.links a {{
                color: var(--primary); text-decoration: none; font-size: 0.9em;
                border: 1px solid var(--border); border-radius: 999px; padding: 6px 12px;
                background: var(--card-bg);
            }}
            .stats {{ opacity: 0.8; font-size: 0.9em; margin: 4px 0 16px; }}
            .toolbar {{ display: flex; gap: 10px; margin: 16px 0; }}
            input[type="search"] {{
                flex: 1; font-size: 16px; padding: 10px 14px;
                border-radius: 10px; border: 1px solid var(--border);
                background: var(--card-bg); color: var(--text);
            }}
            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
                gap: 15px;
                margin-bottom: 30px;
            }}
            .dir-card {{
                background: var(--card-bg);
                border: 1px solid var(--border);
                border-radius: 12px;
                padding: 15px;
            }}
            .dir-card h3 {{ margin: 0; overflow-wrap: anywhere; }}
            .dir-card a {{ color: var(--primary); text-decoration: none; }}
            .dir-card p {{ margin: 6px 0 10px; font-size: 0.9em; opacity: 0.8; }}
            .card-actions, .file-actions {{ display: flex; gap: 8px; flex-wrap: wrap; }}
            .btn {{
                appearance: none; border: 1px solid var(--border); border-radius: 8px;
                background: var(--primary); color: #fff; padding: 8px 12px; min-height: 40px;
                font-size: 0.9em; cursor: pointer; text-decoration: none; display: inline-flex;
                align-items: center;
            }}
            .btn.ghost {{ background: transparent; color: var(--text); }}
            #dropzone {{
                border: 2px dashed var(--border);
                border-radius: 12px;
                padding: 32px 20px;
                text-align: center;
                background: var(--card-bg);
                cursor: pointer;
                transition: border-color 0.2s;
            }}
            #dropzone.dragover {{ border-color: var(--primary); }}
            #status {{ margin-top: 12px; font-weight: 600; }}
            #uploadList, #recentList {{ list-style: none; padding: 0; margin: 12px 0; display: grid; gap: 10px; }}
            #uploadList li, #recentList li {{
                background: var(--card-bg); border: 1px solid var(--border);
                border-radius: 10px; padding: 10px 12px; font-size: 0.9em;
                display: flex; flex-wrap: wrap; gap: 8px; align-items: center; justify-content: space-between;
            }}
            .file-name {{ overflow-wrap: anywhere; flex: 1 1 200px; }}
            .empty {{ opacity: 0.7; }}
            @media (max-width: 600px) {{
                body {{ padding: 12px; }}
                .grid {{ grid-template-columns: 1fr; }}
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <header class="top">
                <h1>📂 Content Hub</h1>
                <nav class="links">
                    <a href="/pwa/">📱 App</a>
                    <a href="/wayfinder">🧭 Wayfinder</a>
                    <a href="/pull-requests">🔀 PRs</a>
                    <a href="/api/jobs">⚙️ Jobs</a>
                </nav>
            </header>
            <p class="stats">{total_files} files • {total_label} • {len(directories)} folders</p>
            <div class="toolbar">
                <input type="search" id="dirSearch" placeholder="Search folders and files…" aria-label="Search folders">
            </div>
            <h2>Directories</h2>
            <div class="grid" id="dirGrid">
                {dirs_html}
            </div>
            <h2>Recent uploads</h2>
            <p class="empty" id="recentEmpty">Latest shareable files from /uploads — View, Download, or Copy link to share anywhere.</p>
            <ul id="recentList"></ul>
            <h2>Upload &amp; share</h2>
            <div id="dropzone">
                <p><strong>Drag &amp; drop files here or click to select</strong> (multiple allowed)</p>
                <p style="font-size: 0.85em; opacity: 0.75;">Max 50MB each. HTML, PDF, PPT / PPTX, DOC / DOCX, XLS / XLSX, CSV, TXT, Images, Audio, Video, ZIP</p>
                <input type="file" id="fileInput" style="display: none;" multiple>
            </div>
            <div id="status" role="status"></div>
            <ul id="uploadList"></ul>
        </div>
        <script>
            const dropzone = document.getElementById('dropzone');
            const fileInput = document.getElementById('fileInput');
            const status = document.getElementById('status');
            const uploadList = document.getElementById('uploadList');
            const recentList = document.getElementById('recentList');
            const recentEmpty = document.getElementById('recentEmpty');
            const dirSearch = document.getElementById('dirSearch');

            function esc(s) {{
                return String(s).replace(/[&<>"']/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
            }}

            async function copyText(text, btn) {{
                try {{
                    await navigator.clipboard.writeText(text);
                }} catch (e) {{
                    const ta = document.createElement('textarea');
                    ta.value = text;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    ta.remove();
                }}
                if (btn) {{
                    const old = btn.textContent;
                    btn.textContent = 'Copied!';
                    setTimeout(() => btn.textContent = old, 1500);
                }}
            }}

            document.addEventListener('click', (e) => {{
                const btn = e.target.closest('[data-copy-url]');
                if (btn) {{
                    const rel = btn.getAttribute('data-copy-url');
                    copyText(new URL(rel, location.origin).href, btn);
                }}
            }});

            if (dirSearch) {{
                dirSearch.addEventListener('input', () => {{
                    const q = dirSearch.value.toLowerCase();
                    document.querySelectorAll('#dirGrid .dir-card').forEach(card => {{
                        card.style.display = card.textContent.toLowerCase().includes(q) ? '' : 'none';
                    }});
                    document.querySelectorAll('#recentList li').forEach(li => {{
                        li.style.display = li.textContent.toLowerCase().includes(q) ? '' : 'none';
                    }});
                }});
            }}

            async function loadRecent() {{
                try {{
                    const res = await fetch('/admin/static/uploads/status');
                    if (!res.ok) return;
                    const data = await res.json();
                    const files = (data.files || []).slice(-12).reverse();
                    if (!files.length) return;
                    if (recentEmpty) recentEmpty.style.display = 'none';
                    recentList.innerHTML = files.map(f => {{
                        const url = '/uploads/' + encodeURIComponent(f.name).replace(/%2F/g, '/');
                        return '<li><span class="file-name">📄 ' + esc(f.name) + '</span>'
                            + '<span class="file-actions">'
                            + '<a class="btn" href="' + esc(url) + '" target="_blank" rel="noopener">View</a>'
                            + '<a class="btn ghost" href="' + esc(url) + '" download>Download</a>'
                            + '<button class="btn ghost" data-copy-url="' + esc(url) + '">Copy link</button>'
                            + '</span></li>';
                    }}).join('');
                }} catch (e) {{}}
            }}
            loadRecent();

            dropzone.addEventListener('click', () => fileInput.click());
            dropzone.addEventListener('dragover', (e) => {{
                e.preventDefault();
                dropzone.classList.add('dragover');
            }});
            dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
            dropzone.addEventListener('drop', (e) => {{
                e.preventDefault();
                dropzone.classList.remove('dragover');
                if(e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
            }});
            fileInput.addEventListener('change', () => {{
                if(fileInput.files.length) uploadFiles(fileInput.files);
                fileInput.value = '';
            }});

            async function uploadFiles(fileList) {{
                let pwd = sessionStorage.getItem('admin_secret');
                if(!pwd) {{
                    pwd = prompt("Enter admin secret:");
                    if(!pwd) return;
                    sessionStorage.setItem('admin_secret', pwd);
                }}
                for (const file of fileList) {{
                    await uploadOne(file, pwd);
                }}
                loadRecent();
            }}

            async function uploadOne(file, pwd) {{
                const li = document.createElement('li');
                li.innerHTML = '<span class="file-name">⏳ ' + esc(file.name) + '</span><span>Uploading…</span>';
                uploadList.prepend(li);

                const formData = new FormData();
                formData.append('file', file);

                status.textContent = 'Uploading ' + file.name + '…';

                try {{
                    const res = await fetch('/admin/upload', {{
                        method: 'POST',
                        headers: {{ 'X-Admin-Secret': pwd }},
                        body: formData
                    }});
                    const data = await res.json();
                    if(res.ok) {{
                        const abs = new URL(data.url, location.origin).href;
                        li.innerHTML = '<span class="file-name">✅ ' + esc(data.filename) + '</span>'
                            + '<span class="file-actions">'
                            + '<a class="btn" href="' + esc(data.url) + '" target="_blank" rel="noopener">View</a>'
                            + '<a class="btn ghost" href="' + esc(data.url) + '" download>Download</a>'
                            + '<button class="btn ghost" data-copy-url="' + esc(data.url) + '">Copy link</button>'
                            + '</span>';
                        status.textContent = 'Success! Shareable URL ready — use Copy link to share.';
                        status.style.color = 'green';
                    }} else {{
                        li.innerHTML = '<span class="file-name">❌ ' + esc(file.name) + '</span><span>' + esc(data.detail || ('HTTP ' + res.status)) + '</span>';
                        status.textContent = 'Error: ' + (data.detail || ('HTTP ' + res.status));
                        status.style.color = 'red';
                        if(res.status === 401) sessionStorage.removeItem('admin_secret');
                    }}
                }} catch (e) {{
                    li.innerHTML = '<span class="file-name">❌ ' + esc(file.name) + '</span><span>' + esc(e.message) + '</span>';
                    status.textContent = 'Upload failed: ' + e.message;
                    status.style.color = 'red';
                }}
            }}
        </script>
    </body>
    </html>
    """

# Include Wayfinder & Pull Requests routers
app.include_router(wayfinder_router)
app.include_router(pull_requests_router)


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
    router_owned = {"wayfinder", "pull-requests"}
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
