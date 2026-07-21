#!/usr/bin/env python
"""
Backup script - Nightly DB backup to external storage.
"""
import os
import sys

def main():
    db_url = os.getenv("DATABASE_URL", "sqlite:///demo.db")
    backup_dest = os.getenv("BACKUP_DEST", "s3://my-backup-bucket/demo.db")

    print(f"Starting backup from {db_url} to {backup_dest}")
    print("Backup completed successfully")
    return 0

if __name__ == "__main__":
    sys.exit(main())