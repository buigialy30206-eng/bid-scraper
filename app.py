"""
招标数据网 — 完整版：注册/登录/订阅/邮件推送
"""

import hashlib
import os
import re
import secrets
import sqlite3
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, Request, HTTPException, Form, Cookie, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
import requests

BASE = Path(__file__).parent
DB_PATH = BASE / "bids.db"

app = FastAPI(title="招标数据网", version="2.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
async def startup_seed():
    """Auto-create tables and seed data if empty."""
    init_all()
    db = get_db()
    count = db.execute("SELECT COUNT(*) as c FROM bids").fetchone()["c"]
    db.close()
    if count == 0:
        print("[Startup] Empty database, running scraper...")
        try:
            import subprocess, sys
            subprocess.run([sys.executable, str(BASE / "scraper.py")], timeout=120)
        except Exception as e:
            print(f"[Startup] Scraper failed: {e}")

# ============ DATABASE ============

def get_db():
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    return db

def init_all():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS bids (
            id TEXT PRIMARY KEY, title TEXT, url TEXT, category TEXT,
            sub_category TEXT, pub_date TEXT, purchaser TEXT, location TEXT,
            project_type TEXT, budget TEXT, content TEXT,
            crawled_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            keywords TEXT DEFAULT '',
            plan TEXT DEFAULT 'free',
            expire_date TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_bids_date ON bids(pub_date);
        CREATE INDEX IF NOT EXISTS idx_bids_loc ON bids(location);
    """)
    db.commit()
    db.close()

init_all()

# ============ AUTH ============

def hash_password(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    db = get_db()
    db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    db.execute("INSERT INTO sessions (token, user_id) VALUES (?,?)", (token, user_id))
    db.commit()
    db.close()
    return token

def get_user_from_cookie(token: str) -> Optional[dict]:
    if not token:
        return None
    db = get_db()
    row = db.execute("SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token=?", (token,)).fetchone()
    db.close()
    return dict(row) if row else None

def is_premium(user: dict) -> bool:
    if not user:
        return False
    exp = user.get("expire_date", "")
    if exp and exp >= datetime.now().strftime("%Y-%m-%d"):
        return True
    return False

# ============ EMAIL ============

def send_email(to: str, subject: str, body: str):
    """Send email via QQ SMTP."""
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    if not smtp_user or not smtp_pass:
        print("SMTP not configured, skipping email")
        return

    msg = MIMEText(body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to

    try:
        server = smtplib.SMTP_SSL("smtp.qq.com", 465, timeout=10)
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to], msg.as_string())
        server.quit()
    except Exception as e:
        print(f"Email failed: {e}")

# ============ HTML PAGES ============

BASE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;color:#1a1a2e;line-height:1.6}
.container{max-width:1200px;margin:0 auto;padding:0 20px}
.topbar{background:#fff;border-bottom:1px solid #e5e7eb;padding:0 20px;position:sticky;top:0;z-index:100;box-shadow:0 1px 3px rgba(0,0,0,0.05)}
.topbar-inner{max-width:1200px;margin:0 auto;display:flex;justify-content:space-between;align-items:center;height:60px}
.topbar .logo{font-size:20px;font-weight:700;color:#1a56db;text-decoration:none}
.topbar .logo span{font-size:14px;color:#6b7280;font-weight:400;margin-left:8px}
.topbar nav a{color:#4b5563;text-decoration:none;font-size:14px;margin-left:20px;padding:8px 14px;border-radius:6px;transition:all .2s}
.topbar nav a:hover{background:#f3f4f6;color:#1a56db}
.topbar nav .btn-primary{background:#1a56db;color:#fff;font-weight:600}
.topbar nav .btn-primary:hover{background:#1e40af;color:#fff}
.hero{background:linear-gradient(135deg,#1e3a5f,#1a56db);color:#fff;padding:50px 20px;text-align:center;margin-bottom:30px}
.hero h1{font-size:32px;font-weight:800;margin-bottom:10px}
.hero p{font-size:16px;opacity:.9;max-width:600px;margin:0 auto}
.search-card{background:#fff;border-radius:12px;padding:20px;margin:-20px auto 30px;max-width:1100px;box-shadow:0 4px 24px rgba(0,0,0,0.08);position:relative;z-index:10}
.search-row{display:flex;gap:10px;flex-wrap:wrap}
.search-row input,.search-row select{padding:12px 16px;border:2px solid #e5e7eb;border-radius:8px;font-size:14px;flex:1;min-width:140px;transition:border-color .2s}
.search-row input:focus,.search-row select:focus{outline:none;border-color:#1a56db}
.search-row button{padding:12px 28px;background:#1a56db;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:background .2s}
.search-row button:hover{background:#1e40af}
.stats-bar{display:flex;gap:15px;margin:15px 0 0;font-size:13px;color:#6b7280}
.stats-bar span{display:inline-flex;align-items:center;gap:4px}
.bid-list{padding:0 0 30px}
.bid-card{background:#fff;border-radius:10px;padding:20px;margin-bottom:12px;border:1px solid #e5e7eb;transition:all .2s;display:flex;gap:16px;align-items:flex-start}
.bid-card:hover{border-color:#1a56db;box-shadow:0 2px 12px rgba(26,86,219,0.08)}
.bid-card .bid-icon{width:40px;height:40px;background:#eff6ff;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}
.bid-card .bid-body{flex:1;min-width:0}
.bid-card .bid-title{font-size:15px;font-weight:600;color:#111827;text-decoration:none;line-height:1.4;display:block;margin-bottom:6px}
.bid-card .bid-title:hover{color:#1a56db}
.bid-card .bid-info{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;color:#6b7280}
.bid-card .bid-info span{display:inline-flex;align-items:center;gap:3px;background:#f9fafb;padding:3px 10px;border-radius:20px}
.bid-card .bid-badge{font-size:11px;font-weight:600;padding:3px 8px;border-radius:4px;text-transform:uppercase;letter-spacing:.5px}
.badge-gkzb{background:#fef3c7;color:#92400e}.badge-jzxcs{background:#dbeafe;color:#1e40af}
.badge-zbjg{background:#d1fae5;color:#065f46}.badge-qtgg{background:#f3f4f6;color:#4b5563}
.empty-state{text-align:center;padding:60px 20px;color:#9ca3af}
.locked-section{text-align:center;padding:30px;background:#f9fafb;border-radius:12px;border:2px dashed #e5e7eb;margin:20px 0}
.locked-section h3{font-size:18px;color:#374151;margin-bottom:8px}
.locked-section p{color:#6b7280;font-size:14px;margin-bottom:15px}
.locked-section .btn{display:inline-block;padding:12px 28px;background:#1a56db;color:#fff;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px}
.form-card{max-width:440px;margin:40px auto;background:#fff;border-radius:16px;padding:40px;box-shadow:0 4px 24px rgba(0,0,0,0.06)}
.form-card h2{font-size:24px;font-weight:700;text-align:center;margin-bottom:8px;color:#111827}
.form-card .subtitle{text-align:center;color:#6b7280;font-size:14px;margin-bottom:24px}
.form-card label{display:block;font-size:14px;font-weight:500;color:#374151;margin-bottom:4px}
.form-card input,.form-card select{width:100%;padding:12px 14px;border:2px solid #e5e7eb;border-radius:8px;font-size:14px;margin-bottom:16px;transition:border-color .2s}
.form-card input:focus{outline:none;border-color:#1a56db}
.form-card .btn-full{width:100%;padding:13px;background:#1a56db;color:#fff;border:none;border-radius:8px;font-size:15px;font-weight:600;cursor:pointer;transition:background .2s}
.form-card .btn-full:hover{background:#1e40af}
.form-card .footer-text{text-align:center;font-size:13px;color:#6b7280;margin-top:16px}
.form-card .footer-text a{color:#1a56db;text-decoration:none;font-weight:500}
.pricing-section{text-align:center;padding:20px 0 40px}
.pricing-section h2{font-size:28px;font-weight:800;color:#111827;margin-bottom:8px}
.pricing-section .subtitle{color:#6b7280;margin-bottom:30px}
.pricing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:20px;max-width:1000px;margin:0 auto}
.plan-card{background:#fff;border:2px solid #e5e7eb;border-radius:16px;padding:32px;text-align:center;transition:all .2s}
.plan-card:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,0,0,0.08)}
.plan-card.featured{border-color:#1a56db;box-shadow:0 4px 20px rgba(26,86,219,0.12);position:relative}
.plan-card.featured::before{content:"推荐";position:absolute;top:12px;right:12px;background:#1a56db;color:#fff;font-size:11px;padding:3px 10px;border-radius:20px;font-weight:600}
.plan-card h3{font-size:20px;font-weight:700;margin-bottom:4px;color:#111827}
.plan-card .plan-price{font-size:42px;font-weight:800;color:#1a56db;margin:16px 0}
.plan-card .plan-price sub{font-size:16px;font-weight:400;color:#9ca3af}
.plan-card ul{list-style:none;text-align:left;margin:20px 0}
.plan-card ul li{padding:8px 0;font-size:14px;color:#4b5563;display:flex;align-items:center;gap:8px}
.plan-card ul li::before{content:"✓";color:#10b981;font-weight:700;font-size:16px}
.plan-card .btn-plan{display:block;padding:12px;border-radius:8px;font-weight:600;font-size:14px;text-decoration:none;transition:all .2s}
.plan-card .btn-plan-outline{border:2px solid #1a56db;color:#1a56db}
.plan-card .btn-plan-outline:hover{background:#1a56db;color:#fff}
.plan-card .btn-plan-solid{background:#1a56db;color:#fff}
.plan-card .btn-plan-solid:hover{background:#1e40af}
.alert{padding:14px 18px;border-radius:8px;margin:16px 0;font-size:14px;display:flex;align-items:center;gap:8px}
.alert-success{background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0}
.alert-error{background:#fef2f2;color:#991b1b;border:1px solid #fecaca}
.admin-table{width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.04)}
.admin-table th{background:#f8fafc;padding:14px 16px;text-align:left;font-size:13px;font-weight:600;color:#64748b;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #e5e7eb}
.admin-table td{padding:14px 16px;font-size:14px;border-bottom:1px solid #f1f5f9;color:#334155}
.admin-table tr:hover{background:#f8fafc}
.btn-sm{padding:6px 16px;font-size:12px;border-radius:6px;text-decoration:none;font-weight:600;display:inline-block}
.btn-success{background:#10b981;color:#fff}.btn-success:hover{background:#059669}
.footer{text-align:center;padding:40px 20px;color:#9ca3af;font-size:13px;border-top:1px solid #e5e7eb;margin-top:40px}
</style>
</head>
<body>
<div class="topbar">
    <div class="topbar-inner">
        <a href="/" class="logo">📋 招标数据网 <span>政府采购公告实时查询</span></a>
        <nav>
            {nav_links}
        </nav>
    </div>
</div>
<div class="hero">
    <h1>招标公告，一搜即达</h1>
    <p>覆盖中国政府采购网全部公告，免费查询最新招标信息</p>
</div>
<div class="container">
{content}
</div>
<div class="footer">数据来源：中国政府采购网 (ccgp.gov.cn) | 每日自动更新 | 招标数据网 © 2026</div>
</body>
</html>"""

# ============ PAGES ============

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request, keyword: str = Query(""), category: str = Query(""), location: str = Query("")):
    user = get_user_from_cookie(request.cookies.get("session"))
    premium = is_premium(user)

    db = get_db()
    total = db.execute("SELECT COUNT(*) as c FROM bids").fetchone()["c"]
    last = db.execute("SELECT pub_date FROM bids ORDER BY pub_date DESC LIMIT 1").fetchone()
    last_update = last["pub_date"] if last else "暂无"

    # Premium: full data, Free: 50 records max
    limit_clause = "" if premium else "LIMIT 50"

    sql = f"SELECT * FROM bids WHERE 1=1"
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
    if not premium:
        sql += " LIMIT 50"
    bids = [dict(r) for r in db.execute(sql, tuple(params)).fetchmany(50)]
    db.close()

    bid_html = ""
    for bid in bids:
        bid_html += f"""
        <div class="bid-card">
            <div class="bid-icon">📄</div>
            <div class="bid-body">
                <a class="bid-title" href="{bid['url']}" target="_blank">{bid['title']}</a>
                <div class="bid-info">
                    <span class="bid-badge badge-gkzb">{bid['sub_category'] or '公告'}</span>
                    <span>📍 {bid['location'] or '未指定'}</span>
                    <span>🏢 {bid['purchaser'] or '未指定'}</span>
                    <span>📅 {bid['pub_date'] or ''}</span>
                </div>
            </div>
        </div>"""

    if not premium:
        bid_html += f"""
        <div class="locked-section">
            <h3>🔒 仅显示 50 条数据</h3>
            <p>订阅专业版查看全部 {total} 条历史公告 + 每日关键词推送</p>
            <a href="/pricing" class="btn">¥99/月 立即订阅</a>
        </div>"""

    nav = (f'<a href="/">首页</a><a href="#">免费公告</a><a href="/pricing" class="btn-primary">💎 升级专业版</a>'
           if not premium else
           '<a href="/">首页</a><a href="#">免费公告</a><span style="font-size:13px;color:#10b981;font-weight:600">✅ 专业版</span>')
    if user:
        nav += f' <a href="/admin">管理</a> <a href="/logout" style="color:#ef4444">退出</a>'
    else:
        nav += ' <a href="/login">登录</a> <a href="/register">注册</a>'

    content = f"""
    <div class="search-card">
        <form class="search-row" method="get" action="/">
            <input type="text" name="keyword" placeholder="🔍 搜索关键词：项目名称 / 采购单位..." value="{keyword}">
            <select name="category">
                <option value="">📂 全部类型</option>
                <option value="公开招标公告" {'selected' if category=='公开招标公告' else ''}>公开招标</option>
                <option value="竞争性磋商公告" {'selected' if category=='竞争性磋商公告' else ''}>竞争性磋商</option>
                <option value="竞争性谈判公告" {'selected' if category=='竞争性谈判公告' else ''}>竞争性谈判</option>
                <option value="中标公告" {'selected' if category=='中标公告' else ''}>中标公告</option>
            </select>
            <input type="text" name="location" placeholder="📍 地区：武汉 / 北京 / 广东..." value="{location}">
            <button type="submit">搜索</button>
        </form>
        <div class="stats-bar">
            <span>📊 共 {total} 条公告</span>
            <span>📅 最新：{last_update}</span>
            {'<span style="color:#1a56db">✅ 专业版 · 全量数据</span>' if premium else '<span style="color:#f59e0b">⚠ 免费版 · 仅50条</span>'}
        </div>
    </div>
    <div class="bid-list">
        {bid_html if bids else '<div class="empty-state">📭 暂无匹配公告</div>'}
    </div>"""

    return BASE_HTML.replace("{title}", "招标数据网").replace("{nav_links}", nav).replace("{content}", content)


@app.get("/register", response_class=HTMLResponse)
async def register_page():
    content = """
    <div class="form-card">
        <h2>创建账号</h2>
        <p class="subtitle">注册后即可免费查询招标公告</p>
        <form method="post" action="/register">
            <label>邮箱地址</label>
            <input type="email" name="email" placeholder="you@email.com" required>
            <label>密码</label>
            <input type="password" name="password" placeholder="最少6位字符" required minlength="6">
            <label>关注关键词（选填）</label>
            <input type="text" name="keywords" placeholder="如：建筑 医疗 IT 设备">
            <button type="submit" class="btn-full">注册</button>
        </form>
        <p class="footer-text">已有账号？<a href="/login">立即登录 →</a></p>
    </div>"""
    nav = '<a href="/login">登录</a>'
    return BASE_HTML.replace("{title}", "注册").replace("{nav_links}", nav).replace("{content}", content)


@app.post("/register")
async def register_post(email: str = Form(...), password: str = Form(...), keywords: str = Form("")):
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if existing:
        db.close()
        return HTMLResponse("<script>alert('该邮箱已注册');location.href='/register'</script>")

    h = hash_password(password)
    db.execute("INSERT INTO users (email, password_hash, keywords) VALUES (?,?,?)", (email, h, keywords))
    db.commit()
    user_id = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()["id"]
    db.close()

    token = create_session(user_id)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("session", token, httponly=True, max_age=86400*30)
    return resp


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    content = """
    <div class="form-card">
        <h2>登录账号</h2>
        <p class="subtitle">欢迎回来，查询最新招标公告</p>
        <form method="post" action="/login">
            <label>邮箱地址</label>
            <input type="email" name="email" placeholder="you@email.com" required>
            <label>密码</label>
            <input type="password" name="password" placeholder="输入密码" required>
            <button type="submit" class="btn-full">登录</button>
        </form>
        <p class="footer-text">没有账号？<a href="/register">立即注册 →</a></p>
    </div>"""
    nav = '<a href="/register">注册</a>'
    return BASE_HTML.replace("{title}", "登录").replace("{nav_links}", nav).replace("{content}", content)


@app.post("/login")
async def login_post(email: str = Form(...), password: str = Form(...)):
    db = get_db()
    h = hash_password(password)
    user = db.execute("SELECT * FROM users WHERE email=? AND password_hash=?", (email, h)).fetchone()
    db.close()
    if not user:
        return HTMLResponse("<script>alert('邮箱或密码错误');location.href='/login'</script>")

    token = create_session(user["id"])
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("session", token, httponly=True, max_age=86400*30)
    return resp


@app.get("/logout")
async def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("session")
    return resp


@app.get("/pricing", response_class=HTMLResponse)
async def pricing_page(request: Request):
    user = get_user_from_cookie(request.cookies.get("session"))
    premium = is_premium(user)

    status_html = ""
    if premium:
        status_html = f'<div class="alert alert-success">✅ 您已是专业版会员，到期日：{user["expire_date"]}</div>'

    content = f"""
    {status_html}
    <div class="pricing-section">
        <h2>选择适合你的方案</h2>
        <p class="subtitle">免费开始，随时升级</p>
        <div class="pricing-grid">
            <div class="plan-card">
                <h3>🆓 免费版</h3>
                <div class="plan-price">¥0<sub>/月</sub></div>
                <ul>
                    <li>查看近3天公告</li>
                    <li>基础搜索筛选</li>
                    <li>有限数据量</li>
                </ul>
                <a href="/register" class="btn-plan btn-plan-outline">免费注册</a>
            </div>
            <div class="plan-card featured">
                <h3>💎 专业版</h3>
                <div class="plan-price">¥99<sub>/月</sub></div>
                <ul>
                    <li>全部历史数据</li>
                    <li>高级搜索筛选</li>
                    <li>关键词邮件推送</li>
                    <li>数据导出 Excel</li>
                    <li>每日更新通知</li>
                </ul>
                <a href="/subscribe" class="btn-plan btn-plan-solid">立即订阅</a>
            </div>
            <div class="plan-card">
                <h3>🏢 企业版</h3>
                <div class="plan-price">¥299<sub>/月</sub></div>
                <ul>
                    <li>专业版全部功能</li>
                    <li>5 个子账号</li>
                    <li>定制关键词推送</li>
                    <li>API 接口接入</li>
                    <li>专属技术支持</li>
                </ul>
                <a href="/subscribe?plan=enterprise" class="btn-plan btn-plan-solid">立即订阅</a>
            </div>
        </div>
    </div>"""

    nav = f'<a href="/">首页</a>'
    if user:
        nav += f' <a href="/logout">退出</a>'
    else:
        nav += ' <a href="/login">登录</a>'
    return BASE_HTML.replace("{title}", "定价").replace("{nav_links}", nav).replace("{content}", content)


@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe_page(request: Request, plan: str = "pro", duration: str = "1month"):
    user = get_user_from_cookie(request.cookies.get("session"))
    if not user:
        return RedirectResponse("/login", 303)

    prices = {
        "pro": {"1month": ("99", "30"), "1year": ("799", "365"), "2year": ("1299", "730"), "3year": ("1799", "1095")},
        "enterprise": {"1month": ("299", "30"), "1year": ("2399", "365"), "2year": ("3999", "730"), "3year": ("5499", "1095")},
    }
    duration_names = {"1month": "1个月", "1year": "1年", "2year": "2年", "3year": "3年"}

    price, days = prices.get(plan, prices["pro"]).get(duration, ("99", "30"))
    plan_name = "企业版" if plan == "enterprise" else "专业版"
    dur_name = duration_names.get(duration, "1个月")

    qr_url = os.environ.get("PAY_QR_URL", "")
    qr_html = f'<img src="{qr_url}" style="max-width:200px;border-radius:8px;margin:10px 0" alt="微信收款码">' if qr_url else ''

    savings = {"1month": "", "1year": "省 ¥389", "2year": "省 ¥1,077", "3year": "省 ¥1,769"}
    per_month = {"1month": "¥99/月", "1year": "≈¥67/月", "2year": "≈¥54/月", "3year": "≈¥50/月"}

    options_html = ""
    for d in ["1month", "1year", "2year", "3year"]:
        active = "active" if duration == d else ""
        save = savings[d]
        pm = per_month[d]
        p = prices[plan][d][0]
        options_html += f"""
        <label class="dur-option {active}">
            <input type="radio" name="dur_radio" onchange="location.href='?plan={plan}&duration={d}'" {'checked' if active else ''}>
            <div class="dur-card">
                <div class="dur-name">{duration_names[d]}</div>
                <div class="dur-price">¥{p}</div>
                <div class="dur-sub">{pm}</div>
                {f'<div class="dur-badge">{save}</div>' if save else ''}
            </div>
        </label>"""

    content = f"""<style>
.dur-selector{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:24px}}
.dur-option input{{display:none}}
.dur-option{{cursor:pointer}}
.dur-card{{background:#fff;border:2px solid #e5e7eb;border-radius:12px;padding:16px 10px;text-align:center;transition:all .2s;position:relative}}
.dur-option:hover .dur-card{{border-color:#1a56db!important;box-shadow:0 0 0 3px rgba(26,86,219,0.1)!important}}
.dur-option.active .dur-card{{border-color:#1a56db;background:#eff6ff;box-shadow:0 0 0 3px rgba(26,86,219,0.1)}}
.dur-name{{font-size:14px;font-weight:600;color:#374151;margin-bottom:4px}}
.dur-price{{font-size:22px;font-weight:800;color:#1a56db;line-height:1.2}}
.dur-sub{{font-size:11px;color:#9ca3af;margin-top:2px}}
.dur-badge{{position:absolute;top:-10px;right:-6px;background:linear-gradient(135deg,#f59e0b,#ef4444);color:#fff;font-size:10px;font-weight:700;padding:3px 8px;border-radius:10px;white-space:nowrap}}
@media(max-width:500px){{.dur-selector{{grid-template-columns:repeat(2,1fr)}}}}
</style>
    <div class="form-card" style="max-width:580px">
        <h2>订阅{plan_name}</h2>
        <p class="subtitle">选择时长，扫码支付</p>

        <div class="dur-selector">
            {options_html}
        </div>

        <div style="background:linear-gradient(135deg,#f0f9ff,#e0f2fe);padding:28px;border-radius:16px;margin:20px 0;text-align:center;border:2px solid #bae6fd">
            <p style="font-size:13px;color:#6b7280;margin-bottom:8px">微信扫码支付</p>
            <p style="font-size:28px;font-weight:800;color:#1a56db;margin-bottom:12px">¥{price}</p>
            {qr_html}
            {f'<p style="font-size:12px;color:#9ca3af;margin-top:12px">扫码有问题？加微信：{os.environ.get("WECHAT_ID","")}</p>' if os.environ.get("WECHAT_ID","") else ''}
        </div>
        <form method="post" action="/subscribe">
            <input type="hidden" name="plan" value="{plan}">
            <input type="hidden" name="duration" value="{duration}">
            <label>您的微信账号</label>
            <input type="text" name="pay_account" placeholder="微信号 / 手机号" required>
            <label>转账单号</label>
            <input type="text" name="pay_ref" placeholder="微信转账单号（用于验证）" required>
            <button type="submit" class="btn-full">提交，等待开通</button>
        </form>
        <p class="footer-text">24小时内审核开通，如有问题联系客服</p>
    </div>"""

    nav = f'<a href="/">首页</a> <a href="/logout">退出</a>'
    return BASE_HTML.replace("{title}", "订阅").replace("{nav_links}", nav).replace("{content}", content)


@app.post("/subscribe")
async def subscribe_post(
    request: Request,
    plan: str = Form("pro"),
    duration: str = Form("1month"),
    pay_account: str = Form(""),
    pay_ref: str = Form(""),
):
    user = get_user_from_cookie(request.cookies.get("session"))
    if not user:
        return RedirectResponse("/login", 303)

    days_map = {"1month": 30, "1year": 365, "2year": 730, "3year": 1095}
    days = days_map.get(duration, 30)
    dur_names = {"1month": "1个月", "1year": "1年", "2year": "2年", "3year": "3年"}
    dur_name = dur_names.get(duration, "1个月")

    # Send notification email to admin
    admin_email = os.environ.get("ADMIN_EMAIL", "")
    if admin_email:
        body = f"""
        <h3>新订阅申请</h3>
        <p>用户：{user['email']}</p>
        <p>方案：{plan} · {dur_name}（{days}天）</p>
        <p>付款账号：{pay_account}</p>
        <p>交易号：{pay_ref}</p>
        <p>时间：{datetime.now()}</p>
        """
        send_email(admin_email, f"[招标数据网] 新订阅 - {user['email']}", body)

    content = """
    <div class="form-card" style="text-align:center">
        <h2>订阅申请已提交</h2>
        <p style="margin:20px 0">我们会在24小时内审核并开通。如有疑问请加微信。</p>
        <a href="/" class="btn" style="display:inline-block;padding:10px 24px;background:#1a56db;color:#fff;border-radius:6px;text-decoration:none">返回首页</a>
    </div>"""
    nav = '<a href="/">首页</a>'
    return BASE_HTML.replace("{title}", "提交成功").replace("{nav_links}", nav).replace("{content}", content)


@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    # Simple admin auth via cookie check
    user = get_user_from_cookie(request.cookies.get("session"))
    admin_email = os.environ.get("ADMIN_EMAIL", "admin")
    if not user or user.get("email") != admin_email:
        return HTMLResponse("Access denied", status_code=403)

    db = get_db()
    users = [dict(r) for r in db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()]
    db.close()

    rows = ""
    for u in users:
        exp = u.get("expire_date", "")
        is_active = exp and exp >= datetime.now().strftime("%Y-%m-%d")
        activate_btn = f'<a href="/admin/activate/{u["id"]}" class="btn btn-green btn-sm">开通30天</a>' if not is_active else f'<span style="color:#10b981">✅ 到期 {exp}</span>'
        rows += f"""
        <tr style="border-bottom:1px solid #eee">
            <td style="padding:10px">{u['email']}</td>
            <td>{u.get('keywords','-')}</td>
            <td>{activate_btn}</td>
            <td>{u['created_at']}</td>
        </tr>"""

    content = f"""
    <h2>🔧 管理后台</h2>
    <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:8px;overflow:hidden">
        <tr style="background:#1a56db;color:#fff">
            <th style="padding:12px;text-align:left">邮箱</th>
            <th style="padding:12px;text-align:left">关键词</th>
            <th style="padding:12px;text-align:left">会员状态</th>
            <th style="padding:12px;text-align:left">注册时间</th>
        </tr>
        {rows}
    </table>"""
    nav = '<a href="/">首页</a> <a href="/logout">退出</a>'
    return BASE_HTML.replace("{title}", "管理后台").replace("{nav_links}", nav).replace("{content}", content)


@app.get("/admin/activate/{user_id}")
async def admin_activate(request: Request, user_id: int):
    user = get_user_from_cookie(request.cookies.get("session"))
    admin_email = os.environ.get("ADMIN_EMAIL", "admin")
    if not user or user.get("email") != admin_email:
        return HTMLResponse("Access denied", status_code=403)

    expire = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")
    db = get_db()
    db.execute("UPDATE users SET expire_date=?, plan='pro' WHERE id=?", (expire, user_id))
    db.commit()
    db.close()
    return RedirectResponse("/admin", 303)


@app.post("/api/sync")
async def sync_data(request: Request):
    """Sync endpoint: local scraper pushes new bids here."""
    try:
        data = await request.json()
    except:
        raise HTTPException(400, "Invalid JSON")

    db = get_db()
    count = 0
    for bid in data.get("bids", []):
        existing = db.execute("SELECT id FROM bids WHERE id=?", (bid.get("id", ""),)).fetchone()
        if not existing:
            db.execute(
                """INSERT INTO bids (id, title, url, category, sub_category, pub_date,
                   purchaser, location, project_type, budget, content)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (bid.get("id"), bid.get("title"), bid.get("url"), bid.get("category"),
                 bid.get("sub_category"), bid.get("pub_date"), bid.get("purchaser"),
                 bid.get("location"), bid.get("project_type"), bid.get("budget"),
                 bid.get("content")),
            )
            count += 1
    db.commit()
    db.close()
    return {"status": "ok", "imported": count}


@app.get("/api/export-users")
async def export_users():
    """Export user data for local sync."""
    db = get_db()
    users = [dict(r) for r in db.execute("SELECT email, password_hash, keywords, plan, expire_date, created_at FROM users").fetchall()]
    db.close()
    return {"users": users}


@app.get("/api/export-db")
async def export_db():
    """Download full database for backup."""
    db_path = str(DB_PATH)
    if not os.path.exists(db_path):
        raise HTTPException(404, "No database found")
    from fastapi.responses import FileResponse
    return FileResponse(db_path, media_type="application/octet-stream", filename="bids.db")
