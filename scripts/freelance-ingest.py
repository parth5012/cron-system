#!/usr/bin/env python
"""
Freelance Ingest script - Scans freelance platform email alerts (Upwork, Fiverr, Freelancer, LinkedIn)
and dispatches relevant opportunities to Discord webhook.
Uses local scripts/gmail_freelance_digest.py.
"""
import os
import sys
import subprocess
from pathlib import Path

def main():
    script_dir = Path(__file__).resolve().parent
    digest_script = script_dir / "gmail_freelance_digest.py"

    if not digest_script.exists():
        print(f"ERROR: {digest_script} not found", file=sys.stderr)
        return 1

    print("Running freelance email digest scan (--post mode)...")
    try:
        res = subprocess.run(
            [sys.executable, str(digest_script), "--post"],
            capture_output=True,
            text=True,
            timeout=55
        )
        if res.stdout:
            print(res.stdout)
        if res.stderr:
            print(res.stderr, file=sys.stderr)
        return res.returncode
    except Exception as e:
        print(f"Failed to execute freelance digest script: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())