import os
import yaml
import subprocess
import threading
import time
import json
import requests
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime


@dataclass
class JobConfig:
    name: str
    schedule: str
    secret: str
    timeout_sec: int
    description: str


@dataclass
class RunRecord:
    job: str
    status: str
    exit_code: int
    duration_ms: int
    stdout: str
    stderr: str
    timestamp: str


class CronEngine:
    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or Path(__file__).parent
        self.cron_yaml_path = self.base_dir / "cron.yaml"
        self.scripts_dir = self.base_dir / "scripts"
        self.jobs: Dict[str, JobConfig] = {}
        self.locks: Dict[str, threading.Lock] = {}
        self.log_sink_url: Optional[str] = os.getenv("LOG_SINK_URL")
        self.log_sink_type: str = os.getenv("LOG_SINK_TYPE", "discord")
        self.run_history: List[RunRecord] = []
        self.max_history = 100
        self._load_jobs()

    def _load_jobs(self):
        if not self.cron_yaml_path.exists():
            raise FileNotFoundError(f"cron.yaml not found at {self.cron_yaml_path}")

        with open(self.cron_yaml_path) as f:
            data = yaml.safe_load(f)

        for job_data in data.get("jobs", []):
            secret = job_data["secret"]
            if secret.startswith("${") and secret.endswith("}"):
                env_var = secret[2:-1]
                secret = os.getenv(env_var, "")
                if not secret:
                    # Fallback to literal if env not set (e.g. for testing)
                    secret = f"env-{env_var}-unset"

            job = JobConfig(
                name=job_data["name"],
                schedule=job_data["schedule"],
                secret=secret,
                timeout_sec=job_data.get("timeout_sec", 60),
                description=job_data.get("description", ""),
            )
            self.jobs[job.name] = job
            self.locks[job.name] = threading.Lock()

    def validate_secret(self, name: str, provided_secret: str) -> bool:
        job = self.jobs.get(name)
        if not job:
            return False
        # Also allow global CRON_SECRET matching
        global_secret = os.getenv("CRON_SECRET", "")
        if global_secret and provided_secret == global_secret:
            return True
        return job.secret == provided_secret

    def is_valid_job(self, name: str) -> bool:
        return name in self.jobs

    def get_job(self, name: str) -> Optional[JobConfig]:
        return self.jobs.get(name)

    def _get_script_path(self, name: str) -> Path:
        return self.scripts_dir / f"{name}.py"

    def _run_script(self, name: str, timeout_sec: int) -> tuple[int, str, str, int]:
        script_path = self._get_script_path(name)
        if not script_path.exists():
            return -1, "", f"Script not found: {script_path}", 0

        start_time = time.time()
        try:
            result = subprocess.run(
                ["python", str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                env={**os.environ, "PYTHONPATH": str(self.base_dir)},
            )
            duration_ms = int((time.time() - start_time) * 1000)
            return result.returncode, result.stdout, result.stderr, duration_ms
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start_time) * 1000)
            return -1, "", f"Script timed out after {timeout_sec}s", duration_ms
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            return -1, "", str(e), duration_ms

    def _log_run(self, record: RunRecord):
        self.run_history.append(record)
        if len(self.run_history) > self.max_history:
            self.run_history = self.run_history[-self.max_history:]

        if self.log_sink_url:
            self._send_to_sink(record)

    def _send_to_sink(self, record: RunRecord):
        try:
            if self.log_sink_type == "discord":
                self._send_discord(record)
            elif self.log_sink_type == "webhook":
                self._send_webhook(record)
        except Exception:
            pass

    def _send_discord(self, record: RunRecord):
        color = 0x00FF00 if record.status == "ok" else 0xFF0000
        payload = {
            "embeds": [{
                "title": f"Cron Job: {record.job}",
                "description": f"Status: {record.status.upper()}\nExit Code: {record.exit_code}\nDuration: {record.duration_ms}ms",
                "color": color,
                "fields": [
                    {"name": "STDOUT", "value": record.stdout[:1000] or "empty", "inline": False},
                    {"name": "STDERR", "value": record.stderr[:1000] or "empty", "inline": False},
                ],
                "timestamp": record.timestamp,
            }]
        }
        requests.post(self.log_sink_url, json=payload, timeout=5)

    def _send_webhook(self, record: RunRecord):
        requests.post(self.log_sink_url, json=asdict(record), timeout=5)

    def execute_job(self, name: str) -> RunRecord:
        job = self.get_job(name)
        if not job:
            raise ValueError(f"Job not found: {name}")

        lock = self.locks.get(name)
        if not lock or not lock.acquire(blocking=False):
            return RunRecord(
                job=name,
                status="error",
                exit_code=409,
                duration_ms=0,
                stdout="",
                stderr="Job already running",
                timestamp=datetime.utcnow().isoformat() + "Z",
            )

        try:
            exit_code, stdout, stderr, duration_ms = self._run_script(name, job.timeout_sec)
            status = "ok" if exit_code == 0 else "error"

            record = RunRecord(
                job=name,
                status=status,
                exit_code=exit_code,
                duration_ms=duration_ms,
                stdout=stdout[-5000:],
                stderr=stderr[-5000:],
                timestamp=datetime.utcnow().isoformat() + "Z",
            )
        finally:
            lock.release()

        self._log_run(record)
        return record

    def get_logs(self, name: str, limit: int = 50) -> List[RunRecord]:
        return [r for r in self.run_history if r.job == name][-limit:]


_engine: Optional[CronEngine] = None


def get_engine() -> CronEngine:
    global _engine
    if _engine is None:
        _engine = CronEngine()
    return _engine