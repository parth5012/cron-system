#!/usr/bin/env python
"""
Warmup script - keeps the Render free tier service awake by pinging /health.
This script is called by cron-job.org every 10 minutes.
"""
import os
import sys
import requests

def main():
    render_url = os.getenv("RENDER_URL")
    if not render_url:
        print("RENDER_URL not set, skipping HTTP warmup. Local warmup OK.")
        return 0

    try:
        resp = requests.get(f"{render_url}/health", timeout=10)
        if resp.status_code == 200:
            print(f"Warmup OK: {resp.json()}")
            return 0
        else:
            print(f"Warmup failed: {resp.status_code} {resp.text}", file=sys.stderr)
            return 1
    except Exception as e:
        print(f"Warmup error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())