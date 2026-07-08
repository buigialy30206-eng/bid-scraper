"""
备份脚本 — 从 Render 下载数据库到本地备份目录
每次保存带时间戳的副本，保留最近 30 个备份
"""

import os
import shutil
import time
from datetime import datetime
from pathlib import Path

import requests

RENDER_URL = "https://bid-scraper-4k34.onrender.com/api/export-db"
BACKUP_DIR = Path(r"E:\Android\hermes-skill-or-mcp\bid-scraper\backups")
MAX_BACKUPS = 30


def backup():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    try:
        resp = requests.get(RENDER_URL, timeout=60, proxies=dict(http=None, https=None))
        if resp.status_code != 200:
            print(f"Backup failed: HTTP {resp.status_code}")
            return

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"bids_{timestamp}.db"

        with open(backup_path, "wb") as f:
            f.write(resp.content)

        size_kb = backup_path.stat().st_size / 1024
        print(f"✅ Backup saved: {backup_path.name} ({size_kb:.1f} KB)")

        # Cleanup: keep only last MAX_BACKUPS
        backups = sorted(BACKUP_DIR.glob("bids_*.db"))
        if len(backups) > MAX_BACKUPS:
            for old in backups[:-MAX_BACKUPS]:
                old.unlink()
                print(f"  Removed old: {old.name}")

    except Exception as e:
        print(f"Backup failed: {e}")


if __name__ == "__main__":
    backup()
