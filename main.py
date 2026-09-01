from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

class CacheControlMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.endswith('/') or 'index.html' in path:
            response.headers['Cache-Control'] = 'no-cache'
        elif any(path.endswith(ext) for ext in ['.html', '.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.webm', '.mov', '.pdf', '.svg']):
            response.headers['Cache-Control'] = 'public, max-age=86400'
        return response

from fastapi import FastAPI, Header, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List
import threading

from cron_engine import CronEngine, RunRecord, get_engine

app = FastAPI(title="Cron System", version="1.0.0")

app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(CacheControlMiddleware)


app.mount("/findings/sih", StaticFiles(directory="static/findings", html=True), name="findings-sih")
app.mount("/sih-arch", StaticFiles(directory="static/sih-arch", html=True), name="sih-arch")


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)