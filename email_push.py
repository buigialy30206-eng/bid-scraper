"""
每日邮件推送 — 给已订阅用户发送匹配关键词的新招标公告
由 cron 每天 8:00 执行
"""

import hashlib
import os
import smtplib
import sqlite3
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

DB_PATH = Path(r"E:\Android\hermes-skill-or-mcp\bid-scraper\bids.db")

SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")

def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db

def send_email(to: str, subject: str, body: str):
    if not SMTP_USER:
        print("SMTP not configured")
        return

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = SMTP_USER
    msg["To"] = to

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=10)
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, [to], msg.as_string())
        server.quit()
        print(f"  Sent to {to}")
    except Exception as e:
        print(f"  Failed {to}: {e}")

def main():
    print(f"[{datetime.now()}] Daily email push...")

    db = get_db()
    today = datetime.now().strftime("%Y-%m-%d")

    # Get active premium users with keywords
    users = db.execute("""
        SELECT * FROM users
        WHERE expire_date >= ? AND keywords != ''
    """, (today,)).fetchall()

    print(f"  Active premium users: {len(users)}")

    for user in users:
        keywords = [k.strip() for k in user["keywords"].split() if k.strip()]
        if not keywords:
            continue

        # Find matching bids from today
        bids = []
        for kw in keywords:
            rows = db.execute(
                "SELECT * FROM bids WHERE pub_date LIKE ? AND (title LIKE ? OR content LIKE ?) LIMIT 10",
                (f"%{today}%", f"%{kw}%", f"%{kw}%")
            ).fetchall()
            for row in rows:
                bid = dict(row)
                if bid["id"] not in [b["id"] for b in bids]:
                    bids.append(bid)

        if not bids:
            continue

        # Build email
        bid_html = ""
        for bid in bids[:10]:
            bid_html += f"""
            <tr>
                <td style="padding:10px;border-bottom:1px solid #ddd">
                    <a href="{bid['url']}" style="color:#1a56db;text-decoration:none;font-weight:600">
                        {bid['title'][:80]}
                    </a>
                    <br><span style="font-size:12px;color:#999">
                        {bid['sub_category']} | {bid['location']} | {bid['purchaser']} | {bid['pub_date']}
                    </span>
                </td>
            </tr>"""

        body = f"""
        <div style="max-width:600px;margin:0 auto;font-family:Arial,sans-serif">
            <div style="background:#1a56db;color:#fff;padding:20px;text-align:center">
                <h2>📋 招标数据网 — 每日推送</h2>
                <p>{today}</p>
            </div>
            <div style="padding:20px;background:#fff">
                <h3>匹配关键词：{', '.join(keywords)}</h3>
                <p style="color:#666">今日新增 {len(bids)} 条相关招标公告</p>
                <table style="width:100%;border-collapse:collapse">
                    {bid_html}
                </table>
                <p style="margin-top:20px;text-align:center">
                    <a href="https://bid-scraper-4k34.onrender.com" style="background:#1a56db;color:#fff;padding:12px 30px;border-radius:6px;text-decoration:none">
                        查看更多 →
                    </a>
                </p>
            </div>
        </div>"""

        send_email(user["email"], f"[招标数据网] {today} 新增 {len(bids)} 条 - {keywords[0]}等", body)

    db.close()
    print("  Done.")

if __name__ == "__main__":
    main()
