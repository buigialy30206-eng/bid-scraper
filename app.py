"""
招标数据网站 — FastAPI + SQLite
搜索、筛选、浏览最新招标公告
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

BASE = Path(__file__).parent
DB_PATH = BASE / "bids.db"

app = FastAPI(title="招标数据网", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def query_db(sql: str, params: tuple = (), limit: int = 50) -> list[dict]:
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    rows = db.execute(sql, params).fetchmany(limit)
    db.close()
    return [dict(r) for r in rows]


PAGE_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>招标数据网 — 政府采购公告实时查询</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f7fa; color: #333; }
.container { max-width: 1100px; margin: 0 auto; padding: 20px; }
.header { background: #1a56db; color: #fff; padding: 20px 0; margin-bottom: 20px; }
.header h1 { font-size: 22px; text-align: center; }
.header p { text-align: center; font-size: 14px; opacity: 0.8; margin-top: 5px; }
.search-box { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; }
.search-box input, .search-box select { padding: 10px 14px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; flex: 1; min-width: 150px; }
.search-box button { padding: 10px 24px; background: #1a56db; color: #fff; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
.stats { display: flex; gap: 15px; margin-bottom: 15px; font-size: 14px; color: #666; }
.stats span { background: #fff; padding: 6px 14px; border-radius: 20px; border: 1px solid #e0e0e0; }
.bid-item { background: #fff; padding: 16px; margin-bottom: 10px; border-radius: 8px; border: 1px solid #e8ecf1; transition: box-shadow 0.2s; }
.bid-item:hover { box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
.bid-title { font-size: 16px; font-weight: 600; color: #1a56db; text-decoration: none; display: block; margin-bottom: 8px; }
.bid-title:hover { text-decoration: underline; }
.bid-meta { display: flex; gap: 15px; flex-wrap: wrap; font-size: 13px; color: #666; }
.bid-meta span { background: #f0f3f7; padding: 3px 10px; border-radius: 4px; white-space: nowrap; }
.tag { background: #e8f0fe; color: #1a56db; font-size: 12px; padding: 2px 8px; border-radius: 3px; }
.pagination { text-align: center; margin: 20px 0; }
.pagination a { display: inline-block; padding: 8px 14px; margin: 0 4px; background: #fff; border: 1px solid #ddd; border-radius: 4px; color: #333; text-decoration: none; font-size: 14px; }
.pagination a:hover { background: #1a56db; color: #fff; border-color: #1a56db; }
.footer { text-align: center; padding: 30px; color: #999; font-size: 13px; }
.cta { background: linear-gradient(135deg, #1a56db, #3b82f6); color: #fff; text-align: center; padding: 30px; border-radius: 10px; margin: 30px 0; }
.cta h2 { font-size: 20px; margin-bottom: 10px; }
.cta p { font-size: 14px; opacity: 0.9; margin-bottom: 15px; }
.cta a { display: inline-block; background: #fff; color: #1a56db; padding: 12px 30px; border-radius: 6px; text-decoration: none; font-weight: 600; }
</style>
</head>
<body>
<div class="header">
    <div class="container">
        <h1>📋 招标数据网</h1>
        <p>政府采购公告实时查询 — 数据来源：中国政府采购网</p>
    </div>
</div>
<div class="container">
    <form class="search-box" method="get" action="/">
        <input type="text" name="keyword" placeholder="搜索关键词：项目名称/采购单位..." value="{{ keyword }}">
        <select name="category">
            <option value="">全部类型</option>
            <option value="公开招标公告" {% if category == '公开招标公告' %}selected{% endif %}>公开招标</option>
            <option value="竞争性磋商公告" {% if category == '竞争性磋商公告' %}selected{% endif %}>竞争性磋商</option>
            <option value="竞争性谈判公告" {% if category == '竞争性谈判公告' %}selected{% endif %}>竞争性谈判</option>
            <option value="单一来源公告" {% if category == '单一来源公告' %}selected{% endif %}>单一来源</option>
            <option value="其他公告" {% if category == '其他公告' %}selected{% endif %}>其他公告</option>
            <option value="中标公告" {% if category == '中标公告' %}selected{% endif %}>中标公告</option>
        </select>
        <input type="text" name="location" placeholder="地区：北京/武汉/广东..." value="{{ location }}">
        <button type="submit">🔍 搜索</button>
    </form>

    <div class="stats">
        <span>📊 总数据：{{ total }} 条</span>
        <span>📅 更新时间：{{ last_update }}</span>
    </div>

    {% for bid in bids %}
    <div class="bid-item">
        <a class="bid-title" href="{{ bid.url }}" target="_blank">{{ bid.title }}</a>
        <div class="bid-meta">
            <span class="tag">{{ bid.sub_category }}</span>
            <span>📍 {{ bid.location or '未指定' }}</span>
            <span>🏢 {{ bid.purchaser or '未指定' }}</span>
            <span>📅 {{ bid.pub_date }}</span>
        </div>
    </div>
    {% endfor %}

    {% if not bids %}
    <p style="text-align:center;padding:40px;color:#999;">暂无匹配的招标公告</p>
    {% endif %}

    <div class="cta">
        <h2>📩 不想每天手动查？</h2>
        <p>订阅关键词推送，新招标公告自动发到你的微信/邮箱</p>
        <p style="font-size:24px;font-weight:700;">¥99/月</p>
        <a href="#subscribe">立即订阅</a>
    </div>

    <div class="footer">
        <p>数据来源：中国政府采购网 (ccgp.gov.cn) | 更新时间：{{ last_update }}</p>
    </div>
</div>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request,
    keyword: str = Query(""),
    category: str = Query(""),
    location: str = Query(""),
):
    # 查询统计
    total = query_db("SELECT COUNT(*) as c FROM bids")[0]["c"]
    last = query_db("SELECT pub_date FROM bids ORDER BY pub_date DESC LIMIT 1")
    last_update = last[0]["pub_date"] if last else "暂无"

    # 查询数据
    sql = "SELECT * FROM bids WHERE 1=1"
    params = []
    if keyword:
        sql += " AND (title LIKE ? OR purchaser LIKE ? OR content LIKE ?)"
        kw = f"%{keyword}%"
        params.extend([kw, kw, kw])
    if category:
        sql += " AND sub_category = ?"
        params.append(category)
    if location:
        sql += " AND location LIKE ?"
        params.append(f"%{location}%")

    sql += " ORDER BY pub_date DESC LIMIT 50"
    bids = query_db(sql, tuple(params), limit=50)

    html = PAGE_HTML.replace("{{ keyword }}", keyword).replace("{{ location }}", location)
    html = html.replace("{{ total }}", str(total)).replace("{{ last_update }}", last_update)

    # Simple template rendering
    from jinja2 import Template
    template = Template(html)
    return template.render(
        keyword=keyword,
        category=category,
        location=location,
        total=total,
        last_update=last_update,
        bids=bids,
    )


@app.get("/api/bids")
async def api_bids(
    keyword: str = Query(""),
    category: str = Query(""),
    location: str = Query(""),
    limit: int = Query(50, le=200),
):
    sql = "SELECT * FROM bids WHERE 1=1"
    params = []
    if keyword:
        sql += " AND (title LIKE ? OR purchaser LIKE ?)"
        kw = f"%{keyword}%"
        params.extend([kw, kw])
    if category:
        sql += " AND sub_category = ?"
        params.append(category)
    if location:
        sql += " AND location LIKE ?"
        params.append(f"%{location}%")
    sql += " ORDER BY pub_date DESC"
    return query_db(sql, tuple(params), limit=limit)


@app.get("/api/stats")
async def api_stats():
    total = query_db("SELECT COUNT(*) as c FROM bids")[0]["c"]
    today = datetime.now().strftime("%Y-%m-%d")
    today_count = query_db(
        "SELECT COUNT(*) as c FROM bids WHERE pub_date LIKE ?", (f"%{today}%",)
    )[0]["c"]
    locations = query_db(
        "SELECT location, COUNT(*) as cnt FROM bids WHERE location != '' GROUP BY location ORDER BY cnt DESC LIMIT 10"
    )
    return {"total": total, "today": today_count, "top_locations": locations}
