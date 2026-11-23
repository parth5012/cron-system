#!/usr/bin/env python3
"""
Download SQL Subqueries PPTX Presentation
Usage: python3 download_pptx.py [output_path]
"""
import sys
import urllib.request
from pathlib import Path

def download_pptx(output_path=None):
    """Download the SQL Subqueries PPTX presentation"""
    if output_path is None:
        output_path = Path.home() / "SQL_Subqueries_Presentation.pptx"
    else:
        output_path = Path(output_path)
    
    url = "https://raw.githubusercontent.com/parth5012/cron-system/main/static/sql-subqueries-presentation/SQL_Subqueries_Presentation.pptx"
    
    print(f"Downloading SQL Subqueries PPTX from GitHub...")
    print(f"URL: {url}")
    print(f"Output: {output_path}")
    
    try:
        urllib.request.urlretrieve(url, output_path)
        print(f"✅ Successfully downloaded to: {output_path}")
        print(f"📊 File size: {output_path.stat().st_size / 1024:.1f} KB")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else None
    download_pptx(output)
