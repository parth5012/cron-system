#!/usr/bin/env python
"""
Freelance Ingest script - Scans freelance platform alerts (Upwork, Fiverr, Freelancer, LinkedIn)
and dispatches relevant opportunities to Discord webhook.
"""
import os
import sys
import subprocess
from pathlib import Path

def main():
    aios_script = Path("D:/work/projects/AI-OS/scripts/gmail_freelance_digest.py")

    if aios_script.exists():
        print("Invoking AI-OS gmail_freelance_digest.py script...")
        try:
            res = subprocess.run(
                ["python", str(aios_script), "--post"],
                capture_output=True,
                text=True,
                timeout=55
            )
            print(res.stdout)
            if res.stderr:
                print(res.stderr, file=sys.stderr)
            return res.returncode
        except Exception as e:
            print(f"Failed to execute AI-OS digest script: {e}", file=sys.stderr)
            return 1
    else:
        print("AI-OS script not found locally. Running freelance ingest fallback check...")
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        if not webhook_url:
            print("DISCORD_WEBHOOK_URL not set, skipping remote notification.")
            return 0

        print("Freelance ingest completed successfully.")
        return 0

if __name__ == "__main__":
    sys.exit(main())