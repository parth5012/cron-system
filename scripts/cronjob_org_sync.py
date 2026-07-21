#!/usr/bin/env python
"""
Automated synchronization script for cron-job.org API.
Reads cron.yaml and registers/updates jobs on cron-job.org via REST API v2.

Environment variables required:
- CRONJOB_ORG_API_KEY: Your API Key from cron-job.org Console (Settings -> API)
- RENDER_URL: Your deployed app URL (e.g., https://cron-system.onrender.com)
- CRON_SECRET: Secret header value passed in X-Cron-Secret header
"""
import os
import sys
import yaml
import requests
from pathlib import Path

API_BASE = "https://api.cron-job.org"


def parse_cron_expression(schedule_str: str) -> dict:
    """
    Parses a 5-part cron string into cron-job.org schedule format.
    Format: 'min hour day_of_month month day_of_week'
    Special case: '*/10 * * * *' -> minutes: [0, 10, 20, 30, 40, 50]
    """
    parts = schedule_str.strip().split()
    if len(parts) != 5:
        # Default fallback: run hourly
        return {
            "timezone": "UTC",
            "expiresAt": 0,
            "hours": [-1],
            "mdays": [-1],
            "minutes": [0],
            "months": [-1],
            "wdays": [-1],
        }

    min_p, hour_p, mday_p, month_p, wday_p = parts

    def parse_part(val: str, max_val: int) -> list:
        if val == "*":
            return [-1]
        if val.startswith("*/"):
            step = int(val[2:])
            return list(range(0, max_val, step))
        if "," in val:
            return [int(x) for x in val.split(",")]
        if "-" in val:
            start, end = val.split("-")
            return list(range(int(start), int(end) + 1))
        return [int(val)]

    return {
        "timezone": "UTC",
        "expiresAt": 0,
        "hours": parse_part(hour_p, 24),
        "mdays": parse_part(mday_p, 31),
        "minutes": parse_part(min_p, 60),
        "months": parse_part(month_p, 12),
        "wdays": parse_part(wday_p, 7),
    }


def sync_jobs():
    api_key = os.getenv("CRONJOB_ORG_API_KEY")
    render_url = os.getenv("RENDER_URL")
    cron_secret = os.getenv("CRON_SECRET")

    if not api_key:
        print("Error: CRONJOB_ORG_API_KEY env var not set.", file=sys.stderr)
        return 1

    if not render_url:
        print("Error: RENDER_URL env var not set (e.g. https://my-app.onrender.com).", file=sys.stderr)
        return 1

    render_url = render_url.rstrip("/")

    cron_yaml_path = Path(__file__).parent.parent / "cron.yaml"
    if not cron_yaml_path.exists():
        print(f"Error: cron.yaml not found at {cron_yaml_path}", file=sys.stderr)
        return 1

    with open(cron_yaml_path) as f:
        config = yaml.safe_load(f)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Fetch existing jobs from cron-job.org
    try:
        res = requests.get(f"{API_BASE}/jobs", headers=headers, timeout=10)
        res.raise_for_status()
        existing_jobs = res.json().get("jobs", [])
        existing_map = {j["title"]: j["jobId"] for j in existing_jobs if "title" in j}
    except Exception as e:
        print(f"Failed to fetch existing jobs from cron-job.org: {e}", file=sys.stderr)
        return 1

    jobs_to_sync = config.get("jobs", [])
    print(f"Found {len(jobs_to_sync)} job(s) in cron.yaml to sync...")

    for job in jobs_to_sync:
        name = job["name"]
        target_url = f"{render_url}/cron/{name}"
        schedule_data = parse_cron_expression(job["schedule"])

        job_payload = {
            "job": {
                "url": target_url,
                "enabled": True,
                "saveResponses": True,
                "schedule": schedule_data,
                "requestMethod": 0,  # GET request
                "extendedData": {
                    "headers": {
                        "X-Cron-Secret": cron_secret or ""
                    }
                },
                "title": name,
            }
        }

        if name in existing_map:
            job_id = existing_map[name]
            print(f"Updating job '{name}' (ID: {job_id})...")
            update_url = f"{API_BASE}/jobs/{job_id}"
            resp = requests.patch(update_url, headers=headers, json=job_payload, timeout=10)
            if resp.status_code in [200, 204]:
                print(f"Successfully updated '{name}'.")
            else:
                print(f"Failed to update '{name}': {resp.status_code} {resp.text}", file=sys.stderr)
        else:
            print(f"Creating new job '{name}'...")
            create_url = f"{API_BASE}/jobs"
            resp = requests.put(create_url, headers=headers, json=job_payload, timeout=10)
            if resp.status_code in [200, 201]:
                print(f"Successfully created '{name}'.")
            else:
                print(f"Failed to create '{name}': {resp.status_code} {resp.text}", file=sys.stderr)

    print("Sync complete.")
    return 0


if __name__ == "__main__":
    sys.exit(sync_jobs())