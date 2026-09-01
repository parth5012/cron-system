import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, Header, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

from cron_engine import CronEngine, RunRecord, get_engine


# ---------------------------------------------------------------------------
# Constants & Config
# ---------------------------------------------------------------------------
STATIC_DIR = Path('static')


class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.endswith('/') or 'index.html' in path:
            response.headers['Cache-Control'] = 'no-cache'
        elif any(path.endswith(ext) for ext in ['.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.webm', '.mov', '.pdf', '.svg']):
            response.headers['Cache-Control'] = 'public, max-age=86400'
        return response

app = FastAPI(title="Cron System", version="1.0.0")


ADMIN_SECRET = os.environ.get('ADMIN_SECRET', '')
ALLOWED_EXTENSIONS = {'.html', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.webm', '.mov', '.pdf'}
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50MB

def verify_admin(x_admin_secret: str = Header(None)):
    if not ADMIN_SECRET or x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail='Invalid admin secret')

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(CacheControlMiddleware)




class RunResponse(BaseModel):
    job: str
    status: str
    exit_code: int
    duration_ms: int


class LogResponse(BaseModel):
    job: str
    status: str
    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str
    timestamp: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/cron/{name}", response_model=RunResponse)
async def cron_dispatch(name: str, x_cron_secret: Optional[str] = Header(None)):
    engine = get_engine()

    if not engine.is_valid_job(name):
        raise HTTPException(status_code=404, detail=f"Job not found: {name}")

    if not engine.validate_secret(name, x_cron_secret or ""):
        raise HTTPException(status_code=401, detail="Invalid secret")

    job = engine.get_job(name)
    if job and job.timeout_sec > 25:
        background_tasks = BackgroundTasks()
        background_tasks.add_task(run_job_background, name)
        return JSONResponse(
            status_code=202,
            content={"job": name, "status": "accepted", "exit_code": 0, "duration_ms": 0},
        )

    record = engine.execute_job(name)
    return RunResponse(
        job=record.job,
        status=record.status,
        exit_code=record.exit_code,
        duration_ms=record.duration_ms,
    )


@app.post("/cron/{name}/run", response_model=RunResponse)
async def cron_manual_run(name: str, x_cron_secret: Optional[str] = Header(None)):
    engine = get_engine()

    if not engine.is_valid_job(name):
        raise HTTPException(status_code=404, detail=f"Job not found: {name}")

    if not engine.validate_secret(name, x_cron_secret or ""):
        raise HTTPException(status_code=401, detail="Invalid secret")

    record = engine.execute_job(name)
    return RunResponse(
        job=record.job,
        status=record.status,
        exit_code=record.exit_code,
        duration_ms=record.duration_ms,
    )


@app.get("/cron/{name}/log", response_model=List[LogResponse])
async def cron_log(name: str, x_cron_secret: Optional[str] = Header(None), limit: int = 50):
    engine = get_engine()

    if not engine.is_valid_job(name):
        raise HTTPException(status_code=404, detail=f"Job not found: {name}")

    if not engine.validate_secret(name, x_cron_secret or ""):
        raise HTTPException(status_code=401, detail="Invalid secret")

    records = engine.get_logs(name, limit)
    return [
        LogResponse(
            job=r.job,
            status=r.status,
            exit_code=r.exit_code,
            duration_ms=r.duration_ms,
            stdout=r.stdout,
            stderr=r.stderr,
            timestamp=r.timestamp,
        )
        for r in records
    ]


def run_job_background(name: str):
    engine = get_engine()
    engine.execute_job(name)




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
        'files': [{'name': str(f.relative_to(target)), 'size': f.stat().st_size} for f in sorted(files)],
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
    file: UploadFile = File(...),
    x_admin_secret: str = Header(None)
):
    verify_admin(x_admin_secret)
    
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f'File type {ext} not allowed')
    
    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail=f'File too large. Max {MAX_UPLOAD_SIZE // (1024*1024)}MB')
    
    upload_dir = STATIC_DIR / 'uploads'
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    dest = upload_dir / file.filename
    if dest.exists():
        stem = dest.stem
        dest = upload_dir / f'{stem}_{int(datetime.now().timestamp())}{ext}'
    
    dest.write_bytes(content)
    return {'url': f'/uploads/{dest.name}', 'size': len(content), 'filename': dest.name}

@app.get('/', response_class=HTMLResponse)
async def index():
    directories = []
    if STATIC_DIR.exists():
        for sub in sorted(STATIC_DIR.iterdir()):
            if sub.is_dir():
                files = list(sub.rglob('*'))
                file_list = [f for f in files if f.is_file()]
                total_bytes = sum(f.stat().st_size for f in file_list)
                directories.append({
                    'slug': sub.name,
                    'file_count': len(file_list),
                    'total_size': f"{total_bytes / (1024*1024):.2f} MB" if total_bytes > 1024*1024 else f"{total_bytes / 1024:.2f} KB",
                    'url': f'/{sub.name}'
                })
    
    dirs_html = "".join([
        f"<div class='dir-card'><h3><a href='{d['url']}'>{d['slug']}</a></h3><p>{d['file_count']} files • {d['total_size']}</p></div>"
        for d in directories
    ])

    html = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>📂 Cron System - Content Hub</title>
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
                    --primary: #0d6efd;
                }}
            }}
            body {{ font-family: system-ui, sans-serif; margin: 0; padding: 20px; background: var(--bg); color: var(--text); }}
            .container {{ max-width: 800px; margin: 0 auto; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }}
            .dir-card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 15px; }}
            .dir-card a {{ color: var(--primary); text-decoration: none; }}
            .dir-card p {{ margin: 5px 0 0; font-size: 0.9em; opacity: 0.8; }}
            #dropzone {{
                border: 2px dashed var(--border);
                border-radius: 12px;
                padding: 40px 20px;
                text-align: center;
                background: var(--card-bg);
                cursor: pointer;
                transition: border-color 0.2s;
            }}
            #dropzone.dragover {{ border-color: var(--primary); }}
            #status {{ margin-top: 15px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📂 Content Hub</h1>
            <h2>Directories</h2>
            <div class="grid">
                {dirs_html}
            </div>
            <h2>Upload File</h2>
            <div id="dropzone">
                <p>Drag and drop a file here or click to select</p>
                <p style="font-size: 0.8em; opacity: 0.7;">Max 50MB. HTML, Images, Video, PDF</p>
                <input type="file" id="fileInput" style="display: none;">
            </div>
            <div id="status"></div>
        </div>
        <script>
            const dropzone = document.getElementById('dropzone');
            const fileInput = document.getElementById('fileInput');
            const status = document.getElementById('status');

            dropzone.addEventListener('click', () => fileInput.click());
            dropzone.addEventListener('dragover', (e) => {{
                e.preventDefault();
                dropzone.classList.add('dragover');
            }});
            dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
            dropzone.addEventListener('drop', (e) => {{
                e.preventDefault();
                dropzone.classList.remove('dragover');
                if(e.dataTransfer.files.length) upload(e.dataTransfer.files[0]);
            }});
            fileInput.addEventListener('change', () => {{
                if(fileInput.files.length) upload(fileInput.files[0]);
            }});

            async function upload(file) {{
                let pwd = sessionStorage.getItem('admin_secret');
                if(!pwd) {{
                    pwd = prompt("Enter admin secret:");
                    if(!pwd) return;
                    sessionStorage.setItem('admin_secret', pwd);
                }}
                
                const formData = new FormData();
                formData.append('file', file);
                
                status.textContent = 'Uploading...';
                status.style.color = 'inherit';
                
                try {{
                    const res = await fetch('/admin/upload', {{
                        method: 'POST',
                        headers: {{ 'X-Admin-Secret': pwd }},
                        body: formData
                    }});
                    const data = await res.json();
                    if(res.ok) {{
                        status.textContent = 'Success! View at: ' + data.url;
                        status.style.color = 'green';
                    }} else {{
                        status.textContent = 'Error: ' + data.detail;
                        status.style.color = 'red';
                        if(res.status === 401) sessionStorage.removeItem('admin_secret');
                    }}
                }} catch (e) {{
                    status.textContent = 'Upload failed: ' + e.message;
                    status.style.color = 'red';
                }}
            }}
        </script>
    </body>
    </html>
    """
    return html

def mount_static_dirs(app):
    if not STATIC_DIR.exists():
        return
    for sub in sorted(STATIC_DIR.iterdir()):
        if sub.is_dir():
            app.mount(f"/{sub.name}", StaticFiles(directory=str(sub), html=True), name=f"static-{sub.name}")
            for child in sorted(sub.iterdir()):
                if child.is_dir():
                    app.mount(f"/{sub.name}/{child.name}", StaticFiles(directory=str(child), html=True), name=f"static-{sub.name}-{child.name}")

mount_static_dirs(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)