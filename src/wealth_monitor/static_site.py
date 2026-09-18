from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import shutil

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .database import connect
from .monitor import now, refresh_all, seed_public_snapshot

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
        "id", "source_name", "url", "fetched_at", "status", "http_status",
        "item_count", "error_message",
    ),
}


def restore_state(path: Path = STATE_PATH) -> None:
    if not path.exists():
        return
    state = json.loads(path.read_text("utf-8"))
    with connect() as db:
        for table, columns in STATE_TABLES.items():
            rows = state.get(table, [])
            if not rows:
                continue
            names = ",".join(columns)
            placeholders = ",".join("?" for _ in columns)
            db.executemany(
                f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})",
                [tuple(row.get(column) for column in columns) for row in rows],
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
        }
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", "utf-8")


def render_site(output_dir: Path = OUTPUT_DIR) -> None:
    (output_dir / "products").mkdir(parents=True, exist_ok=True)
    (output_dir / "static").mkdir(exist_ok=True)

    with connect() as db:
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

    counts = {
        "total": len(products),
        "preferred": sum(p["preference_label"] == "符合基础偏好" for p in products),
        "upcoming": sum(p["status"] == "UPCOMING" for p in products),
    }
    generated_at = max((s["fetched_at"] for s in sources), default=now())
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
        counts=counts,
        generated_at=generated_at,
        actions_url=actions_url,
    )
    (output_dir / "index.html").write_text(index, "utf-8")

    detail_template = environment.get_template("static_detail.html")
    for product in products:
        product_events = [e for e in events if e["product_key"] == product["product_key"]]
        detail = detail_template.render(product=product, events=product_events)
        (output_dir / "products" / f"{product['id']}.html").write_text(detail, "utf-8")

    shutil.copy2(ROOT / "src" / "wealth_monitor" / "static" / "app.css", output_dir / "static" / "app.css")


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
