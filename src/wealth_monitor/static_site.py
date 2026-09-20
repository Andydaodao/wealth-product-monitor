from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .database import connect
from .monitor import normalize_source_url, now, refresh_all, seed_public_snapshot
from .performance import calculate_performance

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_DIR = ROOT / "src" / "wealth_monitor" / "templates"
STATE_PATH = ROOT / "data" / "cloud_state.json"
OUTPUT_DIR = ROOT / "public"

STATE_TABLES = {
    "products": (
        "id", "product_key", "product_code", "product_name", "manager", "risk_level",
        "product_type", "min_purchase_amount", "min_holding_days", "benchmark_text",
        "sale_start_date", "sale_start_time", "open_start_date", "open_start_time",
        "max_scale", "status", "preference_label", "source_name", "source_url",
        "first_seen_at", "last_seen_at",
    ),
    "events": (
        "id", "product_key", "event_type", "summary", "detected_at", "source_url",
        "fingerprint",
    ),
    "source_runs": (
        "id", "scan_id", "source_name", "url", "fetched_at", "status",
        "http_status", "item_count", "new_count", "error_message",
    ),
    "nav_history": (
        "id", "product_code", "nav_date", "unit_nav", "cumulative_nav",
        "ten_thousand_income", "seven_day_annualized", "source_url",
    ),
}


def load_holdings_catalog() -> list[dict]:
    """Return public product and NAV data used by the browser-only holdings page."""
    with connect() as db:
        products = [dict(row) for row in db.execute(
            "SELECT p.id,p.product_code,p.product_name FROM products p "
            "JOIN (SELECT UPPER(product_code) product_code FROM nav_history "
            "GROUP BY UPPER(product_code) HAVING COUNT(DISTINCT nav_date)>=2) n "
            "ON UPPER(p.product_code)=n.product_code "
            "WHERE p.product_code IS NOT NULL AND p.status='ACTIVE' "
            "ORDER BY p.last_seen_at DESC"
        )]
        nav_rows = [dict(row) for row in db.execute(
            "SELECT product_code,nav_date,unit_nav,cumulative_nav,"
            "ten_thousand_income,seven_day_annualized "
            "FROM nav_history ORDER BY product_code,nav_date"
        )]

    nav_by_code: dict[str, list[dict]] = {}
    for row in nav_rows:
        nav_by_code.setdefault(row["product_code"].upper(), []).append({
            "date": row["nav_date"],
            "unit_nav": row["unit_nav"],
            "cumulative_nav": row["cumulative_nav"],
            "ten_thousand_income": row["ten_thousand_income"],
            "seven_day_annualized": row["seven_day_annualized"],
        })

    catalog = []
    seen = set()
    for product in products:
        code = product["product_code"].upper()
        if code in seen:
            continue
        seen.add(code)
        catalog.append({
            "id": product["id"],
            "code": code,
            "name": product["product_name"],
            "nav": nav_by_code.get(code, []),
        })
    return catalog


def restore_state(path: Path = STATE_PATH) -> None:
    if not path.exists():
        return
    state = json.loads(path.read_text("utf-8"))
    with connect() as db:
        for table, columns in STATE_TABLES.items():
            rows = state.get(table, [])
            if not rows:
                continue
            prepared_rows = []
            for row in rows:
                row = dict(row)
                if table in {"products", "events"}:
                    row["product_key"] = row["product_key"].removesuffix("None")
                    row["source_url"] = normalize_source_url(row["source_url"])
                if table == "source_runs":
                    row.setdefault("scan_id", None)
                    row.setdefault("new_count", 0)
                    row["url"] = normalize_source_url(row["url"])
                prepared_rows.append(row)
            names = ",".join(columns)
            placeholders = ",".join("?" for _ in columns)
            db.executemany(
                f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})",
                [tuple(row.get(column) for column in columns) for row in prepared_rows],
            )


def save_state(path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        state = {
            "products": [dict(row) for row in db.execute("SELECT * FROM products ORDER BY id")],
            "events": [dict(row) for row in db.execute("SELECT * FROM events ORDER BY id")],
            "source_runs": [
                dict(row)
                for row in reversed(
                    db.execute("SELECT * FROM source_runs ORDER BY id DESC LIMIT 50").fetchall()
                )
            ],
            "nav_history": [
                dict(row)
                for row in db.execute("SELECT * FROM nav_history ORDER BY product_code,nav_date")
            ],
        }
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")


def render_site(output_dir: Path = OUTPUT_DIR) -> None:
    (output_dir / "products").mkdir(parents=True, exist_ok=True)
    (output_dir / "static").mkdir(exist_ok=True)

    with connect() as db:
        db.execute(
            "UPDATE products SET status='ACTIVE' "
            "WHERE status='UPCOMING' AND open_start_date IS NOT NULL "
            "AND open_start_date<=?",
            (now()[:10],),
        )
        products = [dict(row) for row in db.execute(
            "SELECT * FROM products ORDER BY COALESCE(open_start_date,'9999'), last_seen_at DESC"
        )]
        upcoming = [dict(row) for row in db.execute(
            "SELECT * FROM products WHERE status='UPCOMING' ORDER BY open_start_date LIMIT 5"
        )]
        events = [dict(row) for row in db.execute(
            "SELECT * FROM events ORDER BY detected_at DESC LIMIT 8"
        )]
        sources = [dict(row) for row in db.execute(
            "SELECT s.* FROM source_runs s "
            "JOIN (SELECT source_name,MAX(id) id FROM source_runs GROUP BY source_name) x "
            "ON s.id=x.id ORDER BY s.source_name"
        )]
        recent_scans = [dict(row) for row in db.execute(
            "SELECT scan_id,MIN(fetched_at) fetched_at,SUM(item_count) item_count,"
            "SUM(new_count) new_count,COUNT(*) source_count,"
            "SUM(CASE WHEN status='异常' THEN 1 ELSE 0 END) error_count "
            "FROM source_runs WHERE scan_id IS NOT NULL GROUP BY scan_id "
            "ORDER BY MAX(id) DESC LIMIT 4"
        )]
        nav_rows = [dict(row) for row in db.execute(
            "SELECT * FROM nav_history ORDER BY product_code,nav_date"
        )]

    for scan in recent_scans:
        if scan["error_count"] == 0:
            scan["status"] = "成功"
        elif scan["error_count"] == scan["source_count"]:
            scan["status"] = "异常"
        else:
            scan["status"] = "部分异常"

    counts = {
        "total": len(products),
        "preferred": sum(p["preference_label"] == "符合基础偏好" for p in products),
        "upcoming": sum(p["status"] == "UPCOMING" for p in products),
    }
    generated_at = max((s["fetched_at"] for s in sources), default=now())
    latest_scan = recent_scans[0] if recent_scans else None
    scan_status = latest_scan["status"] if latest_scan else "已完成"
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    actions_url = f"https://github.com/{repository}/actions" if repository else ""

    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(("html", "xml")),
    )
    index = environment.get_template("static_dashboard.html").render(
        products=products,
        upcoming=upcoming,
        events=events,
        sources=sources,
        recent_scans=recent_scans,
        counts=counts,
        generated_at=generated_at,
        scan_status=scan_status,
        actions_url=actions_url,
    )
    (output_dir / "index.html").write_text(index, "utf-8")

    holdings_catalog = load_holdings_catalog()
    for item in holdings_catalog:
        item["detail_url"] = f"products/{item['id']}.html"
    holdings = environment.get_template("holdings.html").render(
        catalog=holdings_catalog,
        home_href="index.html",
        asset_prefix="",
    )
    (output_dir / "holdings.html").write_text(holdings, "utf-8")

    detail_template = environment.get_template("static_detail.html")
    for product in products:
        product_events = [e for e in events if e["product_key"] == product["product_key"]]
        product_nav = [row for row in nav_rows if row["product_code"] == product["product_code"]]
        detail = detail_template.render(
            product=product,
            events=product_events,
            performance=calculate_performance(product_nav),
        )
        (output_dir / "products" / f"{product['id']}.html").write_text(detail, "utf-8")

    shutil.copy2(ROOT / "src" / "wealth_monitor" / "static" / "app.css", output_dir / "static" / "app.css")
    shutil.copy2(ROOT / "src" / "wealth_monitor" / "static" / "holdings.js", output_dir / "static" / "holdings.js")


async def build() -> dict:
    restore_state()
    seed_public_snapshot()
    result = await refresh_all()
    save_state()
    render_site()
    return result


def main() -> None:
    result = asyncio.run(build())
    print(json.dumps(result))


if __name__ == "__main__":
    main()
