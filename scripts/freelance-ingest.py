#!/usr/bin/env python
"""
Freelance Ingest script
Scans freelance platform email alerts (Upwork, Fiverr, Freelancer, LinkedIn, Internshala, Truelancer)
via gmail_freelance_digest.py, and fetches direct postings via freelance_direct_fetcher.py,
dispatching all relevant opportunities to the Discord webhook.
"""
import os
import sys
import subprocess
from pathlib import Path

def main():
    script_dir = Path(__file__).resolve().parent
    digest_script = script_dir / "gmail_freelance_digest.py"
    direct_script = script_dir / "freelance_direct_fetcher.py"
    
    exit_code = 0
    
    # 1. Run Gmail Freelance Digest
    if digest_script.exists():
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
            if res.returncode != 0:
                exit_code = res.returncode
        except Exception as e:
            print(f"Failed to execute freelance email digest script: {e}", file=sys.stderr)
            exit_code = 1
    else:
        print(f"ERROR: {digest_script} not found", file=sys.stderr)
        exit_code = 1
        
    # 2. Run Direct Platforms Fetcher
    if direct_script.exists():
        print("Running freelance direct platforms fetcher (--post mode)...")
        try:
            res = subprocess.run(
                [sys.executable, str(direct_script), "--post"],
                capture_output=True,
                text=True,
                timeout=55
            )
            if res.stdout:
                print(res.stdout)
            if res.stderr:
                print(res.stderr, file=sys.stderr)
            if res.returncode != 0:
                exit_code = res.returncode
        except Exception as e:
            print(f"Failed to execute freelance direct fetcher script: {e}", file=sys.stderr)
            exit_code = 1
    else:
        print(f"ERROR: {direct_script} not found", file=sys.stderr)
        exit_code = 1
        
    return exit_code

if __name__ == "__main__":
    sys.exit(main())
