"""
中国政府采购网 招标公告爬虫
数据源: http://www.ccgp.gov.cn/cggg/zygg/
纯 HTML 渲染，无反爬，requests 直接抓
"""

import re
import sqlite3
import time
import base64
import hashlib
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).parent
DB_PATH = BASE / "bids.db"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 中央公告下面的子分类
CATEGORIES = {
    "gkzb": "公开招标公告",
    "jzxcs": "竞争性磋商公告",
    "jzxtp": "竞争性谈判公告",
    "dyly": "单一来源公告",
    "qtgg": "其他公告",
    "xqgg": "需求公告",
    "zbjg": "中标公告",
}

LIST_URL = "http://www.ccgp.gov.cn/cggg/zygg/index.htm"


def init_db():
    db = sqlite3.connect(str(DB_PATH))
    db.execute("""
        CREATE TABLE IF NOT EXISTS bids (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT,
            sub_category TEXT,
            pub_date TEXT,
            purchaser TEXT,
            location TEXT,
            project_type TEXT,
            budget TEXT,
            content TEXT,
            crawled_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_pub_date ON bids(pub_date)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_category ON bids(category)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_location ON bids(location)")
    db.commit()
    return db


def fetch_list_page() -> list[dict]:
    """抓取列表页，返回所有招标条目"""
    resp = requests.get(LIST_URL, headers=HEADERS, timeout=15)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    # 找到所有公告链接（在 ul.vT-srch-result-list-bid 或类似容器中）
    for a in soup.select("a[target='_blank']"):
        href = a.get("href", "")
        title = a.get("title", "") or a.text.strip()
        if not title or len(title) < 5:
            continue

        # 解析分类：./jzxcs/202607/t20260705_xxx.htm
        match = re.match(r"\./(\w+)/(\d{6})/t(\d{8})_(\d+)\.htm", href)
        if match:
            sub_cat = match.group(1)
            # 生成绝对URL
            url = f"http://www.ccgp.gov.cn/cggg/zygg/{href.lstrip('./')}"
            bid_id = f"{match.group(3)}_{match.group(4)}"

            results.append({
                "id": bid_id,
                "title": title,
                "url": url,
                "sub_category": CATEGORIES.get(sub_cat, sub_cat),
                "category": "中央公告",
            })

    return results


def fetch_detail(url: str) -> dict:
    """抓取详情页，提取结构化信息"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.encoding = "utf-8"
    except Exception:
        return {}

    soup = BeautifulSoup(resp.text, "html.parser")

    # 提取 meta 信息
    meta_date = soup.find("meta", {"name": "PubDate"})
    pub_date = meta_date["content"] if meta_date else ""

    # 提取公告概要表格
    info = {}
    for tr in soup.select("div.table table tr"):
        cells = tr.find_all("td")
        if len(cells) >= 2:
            for i in range(0, len(cells) - 1, 2):
                key = cells[i].text.strip()
                val = cells[i + 1].text.strip() if i + 1 < len(cells) else ""
                if key and val:
                    info[key] = val

    # 提取正文（公告内容）
    content_div = soup.find("div", class_="vF_detail_content")
    content = content_div.get_text("\n", strip=True)[:5000] if content_div else ""

    return {
        "pub_date": pub_date,
        "purchaser": info.get("采购单位", ""),
        "location": info.get("行政区域", ""),
        "project_type": info.get("品目", ""),
        "budget": info.get("预算金额", ""),
        "content": content,
    }


def scrape():
    """主函数：抓取列表+详情，存入数据库"""
    print(f"[{datetime.now()}] 开始抓取中国政府采购网...")
    db = init_db()

    # 1. 抓列表
    items = fetch_list_page()
    print(f"  列表获取: {len(items)} 条")

    new_count = 0
    for item in items:
        # 检查是否已存在
        existing = db.execute("SELECT id FROM bids WHERE id=?", (item["id"],)).fetchone()
        if existing:
            continue

        # 2. 抓详情
        detail = fetch_detail(item["url"])
        time.sleep(0.5)  # 礼貌间隔

        # 3. 存数据库
        db.execute(
            """INSERT INTO bids (id, title, url, category, sub_category, pub_date,
               purchaser, location, project_type, budget, content)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item["id"],
                item["title"],
                item["url"],
                item["category"],
                item["sub_category"],
                detail.get("pub_date", "") or "",
                detail.get("purchaser", "") or "",
                detail.get("location", "") or "",
                detail.get("project_type", "") or "",
                detail.get("budget", "") or "",
                detail.get("content", "") or "",
            ),
        )
        new_count += 1

    db.commit()
    db.close()
    print(f"  新增: {new_count} 条")

    # Sync to Render server
    if new_count > 0:
        try:
            import requests as req
            db2 = sqlite3.connect(str(DB_PATH))
            db2.row_factory = sqlite3.Row

            # Push new bids to Render
            all_bids = [dict(r) for r in db2.execute("SELECT * FROM bids").fetchall()]
            resp = req.post(
                "https://bid-scraper-4k34.onrender.com/api/sync",
                json={"bids": all_bids},
                timeout=60
            )
            print(f"  Sync bids to Render: {resp.status_code}")

            # Pull users from Render, merge into local DB
            resp2 = req.get("https://bid-scraper-4k34.onrender.com/api/export-users", timeout=60)
            if resp2.status_code == 200:
                render_users = resp2.json().get("users", [])
                for u in render_users:
                    ex = db2.execute("SELECT id FROM users WHERE email=?", (u["email"],)).fetchone()
                    if not ex:
                        db2.execute(
                            "INSERT INTO users (email, password_hash, keywords, plan, expire_date, created_at) VALUES (?,?,?,?,?,?)",
                            (u["email"], u["password_hash"], u.get("keywords",""), u.get("plan","free"), u.get("expire_date",""), u.get("created_at",""))
                        )
                db2.commit()
                print(f"  Pulled {len(render_users)} users from Render")

            db2.close()

            # Push updated DB to GitHub
            with open(str(DB_PATH), "rb") as f:
                db_content = base64.b64encode(f.read()).decode()
            headers = {"Authorization": f"token {os.environ.get('GH_TOKEN','')}", "Accept": "application/vnd.github+json"}
            if headers["Authorization"]:
                r = req.get("https://api.github.com/repos/buigialy30206-eng/bid-scraper/contents/bids.db", headers=headers)
                req.put(
                    "https://api.github.com/repos/buigialy30206-eng/bid-scraper/contents/bids.db",
                    headers=headers,
                    json={"message": "Sync bids + users", "content": db_content, "sha": r.json().get("sha", "")}
                )
                print("  Pushed DB to GitHub")
        except Exception as e:
            print(f"  Sync failed: {e}")

    return new_count


if __name__ == "__main__":
    scrape()
