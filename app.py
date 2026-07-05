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
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f5f7fa;color:#333}}
.container{{max-width:1100px;margin:0 auto;padding:20px}}
.header{{background:#1a56db;color:#fff;padding:15px 0;margin-bottom:20px}}
.header .nav{{display:flex;justify-content:space-between;align-items:center;max-width:1100px;margin:0 auto;padding:0 20px}}
.header a{{color:#fff;text-decoration:none;margin-left:15px;font-size:14px}}
.header h1{{font-size:20px}}
.search-box{{display:flex;gap:10px;margin-bottom:15px;flex-wrap:wrap}}
.search-box input,.search-box select{{padding:10px 14px;border:1px solid #ddd;border-radius:6px;font-size:14px;flex:1;min-width:150px}}
.search-box button{{padding:10px 24px;background:#1a56db;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:14px}}
.btn{{display:inline-block;padding:10px 24px;border-radius:6px;text-decoration:none;font-size:14px;font-weight:600;cursor:pointer;border:none}}
.btn-blue{{background:#1a56db;color:#fff}}
.btn-green{{background:#10b981;color:#fff}}
.btn-white{{background:#fff;color:#1a56db;border:2px solid #1a56db}}
.btn-sm{{padding:6px 16px;font-size:13px}}
.bid-item{{background:#fff;padding:16px;margin-bottom:10px;border-radius:8px;border:1px solid #e8ecf1}}
.bid-item:hover{{box-shadow:0 2px 8px rgba(0,0,0,0.08)}}
.bid-title{{font-size:16px;font-weight:600;color:#1a56db;text-decoration:none;display:block;margin-bottom:8px}}
.bid-title:hover{{text-decoration:underline}}
.bid-meta{{display:flex;gap:15px;flex-wrap:wrap;font-size:13px;color:#666}}
.bid-meta span{{background:#f0f3f7;padding:3px 10px;border-radius:4px;white-space:nowrap}}
.tag{{background:#e8f0fe;color:#1a56db;font-size:12px;padding:2px 8px;border-radius:3px}}
.cta{{background:linear-gradient(135deg,#1a56db,#3b82f6);color:#fff;text-align:center;padding:30px;border-radius:10px;margin:30px 0}}
.cta h2{{font-size:20px;margin-bottom:10px}}
.cta a.btn-white{{display:inline-block;padding:12px 30px;border-radius:6px;font-weight:600}}
.form-card{{background:#fff;padding:30px;border-radius:10px;max-width:450px;margin:30px auto;border:1px solid #e8ecf1}}
.form-card h2{{margin-bottom:20px;text-align:center}}
.form-card input{{width:100%;padding:12px;margin-bottom:12px;border:1px solid #ddd;border-radius:6px;font-size:14px}}
.form-card button{{width:100%;padding:12px;background:#1a56db;color:#fff;border:none;border-radius:6px;font-size:15px;cursor:pointer}}
.pricing{{display:flex;gap:20px;flex-wrap:wrap;justify-content:center;margin:30px 0}}
.plan{{background:#fff;border:2px solid #e8ecf1;border-radius:10px;padding:30px;text-align:center;flex:1;min-width:250px}}
.plan.premium{{border-color:#1a56db;box-shadow:0 4px 12px rgba(26,86,219,0.15)}}
.plan h3{{font-size:22px;margin-bottom:10px}}
.plan .price{{font-size:36px;font-weight:700;color:#1a56db;margin:15px 0}}
.plan ul{{list-style:none;text-align:left;margin:20px 0}}
.plan ul li{{padding:6px 0;font-size:14px}}
.plan ul li::before{{content:"✓ ";color:#10b981;font-weight:bold}}
.alert{{padding:12px 16px;border-radius:6px;margin:10px 0;font-size:14px}}
.alert-success{{background:#d1fae5;color:#065f46}}
.alert-error{{background:#fee2e2;color:#991b1b}}
.footer{{text-align:center;padding:30px;color:#999;font-size:13px}}
.locked{{opacity:0.5;pointer-events:none;filter:blur(3px)}}
</style>
</head>
<body>
<div class="header">
    <div class="nav">
        <h1><a href="/" style="color:#fff">📋 招标数据网</a></h1>
        <div>
            {nav_links}
        </div>
    </div>
</div>
<div class="container">
{content}
</div>
<div class="footer">数据来源：中国政府采购网 (ccgp.gov.cn) | 自动化更新</div>
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

    # Premium: full data, Free: last 3 days
    date_filter = "" if premium else " AND pub_date >= date('now', '-3 days')"

    sql = f"SELECT * FROM bids WHERE 1=1{date_filter}"
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
    sql += " ORDER BY pub_date DESC LIMIT 50"
    bids = [dict(r) for r in db.execute(sql, tuple(params)).fetchmany(50)]
    db.close()

    bid_html = ""
    for bid in bids:
        bid_html += f"""
        <div class="bid-item">
            <a class="bid-title" href="{bid['url']}" target="_blank">{bid['title']}</a>
            <div class="bid-meta">
                <span class="tag">{bid['sub_category'] or '公告'}</span>
                <span>📍 {bid['location'] or '未指定'}</span>
                <span>🏢 {bid['purchaser'] or '未指定'}</span>
                <span>📅 {bid['pub_date'] or ''}</span>
            </div>
        </div>"""

    if not premium:
        bid_html += """
        <div class="cta">
            <h2>🔒 仅显示近3天数据</h2>
            <p>订阅专业版查看全部历史招标公告，支持关键词自动推送</p>
            <a href="/pricing" class="btn-white">¥99/月 立即订阅</a>
        </div>
        <div style="text-align:center;color:#999;padding:20px">
            以下为付费内容，共 {locked_count} 条历史公告
        </div>
        """.replace("{locked_count}", str(total - len(bids)))

    nav = f'<a href="/pricing">💎 升级专业版</a>' if not premium else '<span style="color:#fff">✅ 专业版会员</span>'
    if user:
        nav += f' <span style="color:#fff;opacity:0.7">{user["email"]}</span> <a href="/logout">退出</a>'
    else:
        nav += ' <a href="/login">登录</a> <a href="/register">注册</a>'

    content = f"""
    <form class="search-box" method="get" action="/">
        <input type="text" name="keyword" placeholder="搜索：项目名称/采购单位..." value="{keyword}">
        <select name="category">
            <option value="">全部类型</option>
            <option value="公开招标公告" {'selected' if category=='公开招标公告' else ''}>公开招标</option>
            <option value="竞争性磋商公告" {'selected' if category=='竞争性磋商公告' else ''}>竞争性磋商</option>
            <option value="竞争性谈判公告" {'selected' if category=='竞争性谈判公告' else ''}>竞争性谈判</option>
            <option value="中标公告" {'selected' if category=='中标公告' else ''}>中标公告</option>
        </select>
        <input type="text" name="location" placeholder="地区：武汉/北京/广东..." value="{location}">
        <button type="submit">🔍 搜索</button>
    </form>
    <div style="margin-bottom:15px;font-size:14px;color:#666">
        📊 总数据：{total} 条 | 📅 最新：{last_update}
    </div>
    {bid_html}
    """

    return BASE_HTML.replace("{title}", "招标数据网").replace("{nav_links}", nav).replace("{content}", content)


@app.get("/register", response_class=HTMLResponse)
async def register_page():
    content = """
    <div class="form-card">
        <h2>📝 注册账号</h2>
        <form method="post" action="/register">
            <input type="email" name="email" placeholder="邮箱地址" required>
            <input type="password" name="password" placeholder="密码（最少6位）" required minlength="6">
            <input type="text" name="keywords" placeholder="关注关键词（选填，如：建筑 医疗 IT）">
            <button type="submit">注册</button>
        </form>
        <p style="text-align:center;margin-top:15px;font-size:14px">已有账号？<a href="/login">立即登录</a></p>
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
        <h2>🔑 登录</h2>
        <form method="post" action="/login">
            <input type="email" name="email" placeholder="邮箱地址" required>
            <input type="password" name="password" placeholder="密码" required>
            <button type="submit">登录</button>
        </form>
        <p style="text-align:center;margin-top:15px;font-size:14px">没有账号？<a href="/register">立即注册</a></p>
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
    <h2 style="text-align:center;margin:20px 0">选择适合你的方案</h2>
    <div class="pricing">
        <div class="plan">
            <h3>🆓 免费版</h3>
            <div class="price">¥0</div>
            <ul>
                <li>查看近3天公告</li>
                <li>基础搜索筛选</li>
                <li>有限数据量</li>
            </ul>
            <a href="/register" class="btn btn-white">免费注册</a>
        </div>
        <div class="plan premium">
            <h3>💎 专业版</h3>
            <div class="price">¥99<span style="font-size:16px;font-weight:400">/月</span></div>
            <ul>
                <li>全部历史数据</li>
                <li>高级搜索筛选</li>
                <li>关键词邮件推送</li>
                <li>优先数据更新</li>
                <li>导出Excel</li>
            </ul>
            <a href="/subscribe" class="btn btn-blue">立即订阅</a>
        </div>
        <div class="plan">
            <h3>🏢 企业版</h3>
            <div class="price">¥299<span style="font-size:16px;font-weight:400">/月</span></div>
            <ul>
                <li>专业版全部功能</li>
                <li>5个子账号</li>
                <li>定制关键词推送</li>
                <li>API接口</li>
                <li>专属客服</li>
            </ul>
            <a href="/subscribe?plan=enterprise" class="btn btn-blue">联系客服</a>
        </div>
    </div>"""

    nav = f'<a href="/">首页</a>'
    if user:
        nav += f' <a href="/logout">退出</a>'
    else:
        nav += ' <a href="/login">登录</a>'
    return BASE_HTML.replace("{title}", "定价").replace("{nav_links}", nav).replace("{content}", content)


@app.get("/subscribe", response_class=HTMLResponse)
async def subscribe_page(request: Request, plan: str = "pro"):
    user = get_user_from_cookie(request.cookies.get("session"))
    if not user:
        return RedirectResponse("/login", 303)

    price = "299" if plan == "enterprise" else "99"
    plan_name = "企业版" if plan == "enterprise" else "专业版"

    content = f"""
    <div class="form-card" style="max-width:500px">
        <h2>💳 订阅{plan_name} — ¥{price}/月</h2>
        <div style="background:#f9fafb;padding:20px;border-radius:8px;margin:20px 0;text-align:center">
            <p style="font-size:14px;color:#666;margin-bottom:15px">请转账至以下账户，然后提交转账信息</p>
            <p style="font-size:18px;font-weight:600">💰 支付宝/微信</p>
            <p style="font-size:24px;font-weight:700;color:#1a56db">¥{price}</p>
            <p style="font-size:12px;color:#999;margin-top:10px">付款备注：{user['email']}</p>
            <p style="font-size:12px;color:#999">或联系微信：your_wechat_id</p>
        </div>
        <form method="post" action="/subscribe">
            <input type="hidden" name="plan" value="{plan}">
            <input type="text" name="pay_account" placeholder="您的支付宝/微信账号" required>
            <input type="text" name="pay_ref" placeholder="转账单号/交易号（用于验证）" required>
            <button type="submit">提交，等待开通</button>
        </form>
        <p style="text-align:center;margin-top:15px;font-size:12px;color:#999">
            提交后24小时内开通。如需加急请联系微信客服。
        </p>
    </div>"""

    nav = f'<a href="/">首页</a> <a href="/logout">退出</a>'
    return BASE_HTML.replace("{title}", "订阅").replace("{nav_links}", nav).replace("{content}", content)


@app.post("/subscribe")
async def subscribe_post(
    request: Request,
    plan: str = Form("pro"),
    pay_account: str = Form(""),
    pay_ref: str = Form(""),
):
    user = get_user_from_cookie(request.cookies.get("session"))
    if not user:
        return RedirectResponse("/login", 303)

    # Send notification email to admin
    admin_email = os.environ.get("ADMIN_EMAIL", "")
    if admin_email:
        body = f"""
        <h3>新订阅申请</h3>
        <p>用户：{user['email']}</p>
        <p>方案：{plan}</p>
        <p>付款账号：{pay_account}</p>
        <p>交易号：{pay_ref}</p>
        <p>时间：{datetime.now()}</p>
        """
        send_email(admin_email, f"[招标数据网] 新订阅 - {user['email']}", body)

    content = """
    <div class="form-card" style="text-align:center">
        <h2>✅ 订阅申请已提交</h2>
        <p style="margin:20px 0">我们会在24小时内审核并开通。如有疑问请加微信。</p>
        <a href="/" class="btn btn-blue">返回首页</a>
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
