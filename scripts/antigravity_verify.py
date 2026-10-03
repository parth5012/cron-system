"""One-time local check: can this machine renew the agy OAuth token?

Reads the local agy token file, attempts a refresh against Google, and
prints status ONLY (lengths and expiry, never token values).

Usage:
    python scripts/antigravity_verify.py
    ANTIGRAVITY_TOKEN_FILE=~/other-token python scripts/antigravity_verify.py
"""

import json
import os
import sys
from pathlib import Path

import httpx

CLIENT_ID = os.environ.get(
    "ANTIGRAVITY_OAUTH_CLIENT_ID",
    "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com",
)
CLIENT_SECRET = os.environ.get("ANTIGRAVITY_OAUTH_CLIENT_SECRET", "")
TOKEN_FILE = os.environ.get(
    "ANTIGRAVITY_TOKEN_FILE", "~/.gemini/antigravity-cli/antigravity-oauth-token"
)


def main() -> int:
    try:
        data = json.loads(Path(TOKEN_FILE).expanduser().read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"FAIL: cannot read token file: {type(exc).__name__}")
        return 1

    token = data.get("token") or {}
    refresh_token = str(token.get("refresh_token") or "")
    print(f"token file: {TOKEN_FILE}")
    print(f"stored expiry: {token.get('expiry') or 'unknown'}")
    print(f"refresh_token present: {bool(refresh_token)} (len={len(refresh_token)})")
    if not refresh_token:
        print("FAIL: no refresh_token in file; run `agy login` again")
        return 1

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                },
            )
    except Exception as exc:
        print(f"FAIL: token endpoint unreachable: {type(exc).__name__}")
        return 1

    if response.status_code != 200:
        print(f"FAIL: refresh rejected (http={response.status_code})")
        return 1

    try:
        body = response.json() or {}
    except ValueError:
        print("FAIL: token endpoint returned invalid JSON")
        return 1

    fresh = bool(body.get("access_token"))
    print(f"OK: renewal works (new access_token len={len(str(body.get('access_token') or ''))})")
    print(f"expires_in: {body.get('expires_in')}")
    print(f"rotated refresh_token issued: {bool(body.get('refresh_token'))}")
    return 0 if fresh else 1


if __name__ == "__main__":
    sys.exit(main())
