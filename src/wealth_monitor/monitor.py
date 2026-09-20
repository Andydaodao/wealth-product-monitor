from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup
import httpx

from .database import connect
from .config import CONFIG

TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
PRODUCT_URL = "https://www.bocwm.cn/"
NOTICE_URL = "https://www.bocwm.cn/html/1/198/197/index.html"
HEADERS = {"User-Agent": "Personal-Wealth-Product-Monitor/1.0 (+local personal use)"}

# 取自中银理财公开首页的最近快照。首次启动即有可评审界面；联网刷新后按产品代码覆盖。
PUBLIC_SNAPSHOT = [
    {"code": "CYQWFCZ7D2A", "name": "中银理财-稳富纯债7天持有期2号", "days": 7, "nav": "1.014003", "risk": "R2", "min_amount": "1.00元", "sale_date": "2026-04-23", "url": "https://www.bocwm.cn/html/1/4/9494.html"},
    {"code": "CYQWFZQZSGZ14D2A", "name": "中银理财-稳富固收增强指数跟踪策略14天持有期2号", "days": 14, "nav": "1.045413"},
    {"code": "CYQWFXYJX30D3A", "name": "中银理财-稳富信用精选30天持有期产品3号", "days": 30, "nav": "1.037556"},
    {"code": "CYQWFZQQQPZ60D2A", "name": "中银理财-稳富固收增强全球配置60天持有期2号", "days": 60, "nav": "1.033464"},
    {"code": "CYQWFZQHYLD90DA", "name": "中银理财-稳富固收增强行业轮动策略90天持有期", "days": 90, "nav": "1.043303"},
    {"code": "FCYQZQ368DA", "name": "中银理财“福”固收增强368天持有期理财产品", "days": 368, "nav": "1.043822"},
]

NOTICE_SNAPSHOT = [
    {"name": "中银理财-稳富（季增益）010 A份额", "date": "2026-09-28", "url": "https://www.bocwm.cn/html/1/198/197/41315.html"},
    {"name": "中银理财稳富固收双月开3号", "date": "2026-09-17", "url": NOTICE_URL},
]


def now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def normalize_source_url(url: str) -> str:
    parts = urlsplit(url)
    path = re.sub(r"/{2,}", "/", parts.path)
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment))


def preference(name: str, days: int | None, risk: str | None) -> str:
    if risk and risk not in CONFIG["risk_levels"]:
        return "不符合风险偏好"
    if days is not None and days > CONFIG["preferred_holding_days_max"]:
        return "需要进一步研究"
    if risk is None:
        return "信息不足"
    if any(word in name for word in ("纯债", "固收")) and days is not None:
        return "符合基础偏好"
    return "信息不足"


def upsert_product(item: dict, source_name: str, source_url: str) -> bool:
    stamp = now()
    key = item.get("code") or f"{item['name']}|{item.get('date', '')}"
    with connect() as db:
        old = db.execute("SELECT * FROM products WHERE product_key=?", (key,)).fetchone()
        values = {
            "product_key": key, "product_code": item.get("code"), "product_name": item["name"],
            "manager": "中银理财有限责任公司", "risk_level": item.get("risk"),
            "product_type": item.get("type"),
            "min_purchase_amount": item.get("min_amount"), "min_holding_days": item.get("days"),
            "benchmark_text": item.get("benchmark"), "sale_start_date": item.get("sale_date"),
            "sale_start_time": item.get("sale_time"), "open_start_date": item.get("date"),
            "open_start_time": item.get("open_time"), "max_scale": item.get("max_scale"),
            "status": item.get("lifecycle_status") or ("UPCOMING" if item.get("date") and item["date"] > datetime.now(TZ).date().isoformat() else "ACTIVE"),
            "preference_label": preference(item["name"], item.get("days"), item.get("risk")),
            "source_name": source_name, "source_url": source_url,
            "first_seen_at": old["first_seen_at"] if old else stamp, "last_seen_at": stamp,
        }
        if old:
            for column, value in values.items():
                if value is None and old[column] is not None:
                    values[column] = old[column]
        values["preference_label"] = preference(values["product_name"], values["min_holding_days"], values["risk_level"])
        columns = ",".join(values)
        placeholders = ",".join("?" for _ in values)
        updates = ",".join(f"{c}=excluded.{c}" for c in values if c not in {"product_key", "first_seen_at"})
        db.execute(f"INSERT INTO products ({columns}) VALUES ({placeholders}) ON CONFLICT(product_key) DO UPDATE SET {updates}", tuple(values.values()))
        if not old:
            fp = hashlib.sha256(f"{key}|NEW_PRODUCT".encode()).hexdigest()
            db.execute("INSERT OR IGNORE INTO events(product_key,event_type,summary,detected_at,source_url,fingerprint) VALUES(?,?,?,?,?,?)",
                       (key, "NEW_PRODUCT", f"首次发现：{item['name']}", stamp, source_url, fp))
        return old is None


def parse_homepage(html: str) -> list[dict]:
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    matches = re.findall(r"(中银理财[^\n]{3,90}?(?:持有期[^\n]{0,30}|产品))\s+([A-Z][A-Z0-9]{5,})", text)
    products = []
    for name, code in matches:
        days = re.search(r"(\d+)天持有", name)
        products.append({"name": re.sub(r"\s+", "", name), "code": code, "days": int(days.group(1)) if days else None})
    return {p["code"]: p for p in products}.values()


def parse_notice_page(html: str) -> list[dict]:
    products = {}
    for link in BeautifulSoup(html, "html.parser").find_all("a"):
        title = re.sub(r"\s+", "", link.get_text(" ", strip=True))
        if "产品" not in title or not any(kind in title for kind in ("开放预告", "发行公告")):
            continue
        quoted = re.search(r"[“\"]([^”\"]+)[”\"]产品", title)
        name = quoted.group(1) if quoted else re.split(r"产品(?:开放预告|发行公告)", title)[0]
        opened = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日开放", title)
        date = f"{opened.group(1)}-{int(opened.group(2)):02d}-{int(opened.group(3)):02d}" if opened else None
        url = str(link.get("href") or NOTICE_URL)
        if url.startswith("/"):
            url = "https://www.bocwm.cn" + url
        url = normalize_source_url(url)
        item = {"name": name.strip("“”（）()"), "date": date, "url": url}
        if "发行公告" in title and date is None:
            item["lifecycle_status"] = "UPCOMING"
        products[f"{item['name']}|{date or ''}"] = item
    return list(products.values())


def seed_public_snapshot() -> None:
    for item in PUBLIC_SNAPSHOT:
        upsert_product(item, "中银理财产品展示（公开快照）", item.get("url", PRODUCT_URL))
    for item in NOTICE_SNAPSHOT:
        upsert_product(item, "中银理财产品公告（公开快照）", item["url"])
    with connect() as db:
        if not db.execute("SELECT 1 FROM source_runs LIMIT 1").fetchone():
            stamp = now()
            db.executemany(
                "INSERT INTO source_runs(scan_id,source_name,url,fetched_at,status,http_status,item_count,new_count) VALUES(?,?,?,?,?,?,?,?)",
                [
                    (None, "中银理财产品展示（公开快照）", PRODUCT_URL, stamp, "快照", 200, len(PUBLIC_SNAPSHOT), 0),
                    (None, "中银理财产品公告（公开快照）", NOTICE_URL, stamp, "快照", 200, len(NOTICE_SNAPSHOT), 0),
                ],
            )


async def refresh_all() -> dict:
    results = []
    scan_id = datetime.now(TZ).isoformat(timespec="microseconds")
    async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
        for source, url in (("中银理财产品展示", PRODUCT_URL), ("中银理财产品公告", NOTICE_URL)):
            stamp = now()
            try:
                response = await client.get(url)
                response.raise_for_status()
                items = list(parse_homepage(response.text)) if url == PRODUCT_URL else parse_notice_page(response.text)
                new_count = sum(upsert_product(x, source, x.get("url", url)) for x in items)
                with connect() as db:
                    db.execute("INSERT INTO source_runs(scan_id,source_name,url,fetched_at,status,http_status,item_count,new_count) VALUES(?,?,?,?,?,?,?,?)",
                               (scan_id, source, url, stamp, "正常", response.status_code, len(items), new_count))
                results.append({"source": source, "status": "正常", "items": len(items), "new": new_count})
            except Exception as exc:
                message = str(exc)[:240]
                with connect() as db:
                    db.execute("INSERT INTO source_runs(scan_id,source_name,url,fetched_at,status,item_count,new_count,error_message) VALUES(?,?,?,?,?,?,?)",
                               (scan_id, source, url, stamp, "异常", 0, 0, message))
                results.append({"source": source, "status": "异常", "error": message})
    return {"runs": results, "at": now()}
