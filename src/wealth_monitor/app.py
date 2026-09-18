from contextlib import asynccontextmanager
import asyncio
import random
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .database import connect
from .config import CONFIG
from .monitor import refresh_all, seed_public_snapshot

ROOT = Path(__file__).resolve().parents[2]
templates = Jinja2Templates(directory=ROOT / "src" / "wealth_monitor" / "templates")
refresh_lock = asyncio.Lock()


async def monitor_loop() -> None:
    while True:
        app.state.syncing = True
        try:
            async with refresh_lock:
                await refresh_all()
        finally:
            app.state.syncing = False
        delay = CONFIG["scan_interval_minutes"] * 60 + random.randint(0, CONFIG["jitter_seconds"])
        await asyncio.sleep(delay)


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_public_snapshot()
    app.state.syncing = True
    task = asyncio.create_task(monitor_loop())
    yield
    task.cancel()


app = FastAPI(title="中银理财监控", lifespan=lifespan)
app.state.syncing = False
app.mount("/static", StaticFiles(directory=ROOT / "src" / "wealth_monitor" / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, q: str = "", risk: str = "全部", holding: str = "全部", scope: str = "all"):
    where, args = [], []
    if q:
        where.append("(product_name LIKE ? OR product_code LIKE ? OR manager LIKE ?)")
        args += [f"%{q}%"] * 3
    if risk != "全部":
        where.append("risk_level=?"); args.append(risk)
    if holding == "90天以内":
        where.append("min_holding_days<=90")
    if scope in {"UPCOMING", "ACTIVE", "HISTORICAL"}:
        where.append("status=?"); args.append(scope)
    if scope == "WATCHLIST":
        where.append("EXISTS (SELECT 1 FROM watchlist w WHERE w.product_key=products.product_key)")
    clause = " WHERE " + " AND ".join(where) if where else ""
    with connect() as db:
        products = db.execute("SELECT products.*, EXISTS(SELECT 1 FROM watchlist w WHERE w.product_key=products.product_key) is_watched FROM products" + clause + " ORDER BY COALESCE(open_start_date,'9999'), last_seen_at DESC", args).fetchall()
        upcoming = db.execute("SELECT products.*, EXISTS(SELECT 1 FROM watchlist w WHERE w.product_key=products.product_key) is_watched FROM products WHERE status='UPCOMING' ORDER BY open_start_date LIMIT 5").fetchall()
        events = db.execute("SELECT * FROM events ORDER BY detected_at DESC LIMIT 6").fetchall()
        sources = db.execute("SELECT s.* FROM source_runs s JOIN (SELECT source_name,MAX(id) id FROM source_runs GROUP BY source_name) x ON s.id=x.id ORDER BY s.source_name").fetchall()
        counts = db.execute("SELECT COUNT(*) total, SUM(preference_label='符合基础偏好') preferred, SUM(status='UPCOMING') upcoming, (SELECT COUNT(*) FROM watchlist) watched FROM products").fetchone()
    return templates.TemplateResponse(request, "dashboard.html", {"products": products, "upcoming": upcoming, "events": events, "sources": sources, "counts": counts, "q": q, "risk": risk, "holding": holding, "scope": scope, "config": CONFIG, "syncing": request.app.state.syncing})


@app.get("/products/{product_id}", response_class=HTMLResponse)
def product_detail(request: Request, product_id: int):
    with connect() as db:
        product = db.execute("SELECT products.*, EXISTS(SELECT 1 FROM watchlist w WHERE w.product_key=products.product_key) is_watched FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            raise HTTPException(404)
        events = db.execute("SELECT * FROM events WHERE product_key=? ORDER BY detected_at DESC", (product["product_key"],)).fetchall()
    return templates.TemplateResponse(request, "detail.html", {"product": product, "events": events})


@app.post("/api/refresh")
async def refresh():
    if refresh_lock.locked():
        return {"status": "正在检查", "runs": []}
    app.state.syncing = True
    try:
        async with refresh_lock:
            return await refresh_all()
    finally:
        app.state.syncing = False


@app.post("/products/{product_id}/watch")
def toggle_watch(product_id: int):
    with connect() as db:
        product = db.execute("SELECT product_key FROM products WHERE id=?", (product_id,)).fetchone()
        if not product:
            raise HTTPException(404)
        watched = db.execute("SELECT 1 FROM watchlist WHERE product_key=?", (product["product_key"],)).fetchone()
        if watched:
            db.execute("DELETE FROM watchlist WHERE product_key=?", (product["product_key"],))
        else:
            from .monitor import now
            db.execute("INSERT INTO watchlist(product_key,created_at) VALUES(?,?)", (product["product_key"], now()))
    return RedirectResponse(f"/products/{product_id}", status_code=303)


@app.get("/api/products")
def products_api():
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM products ORDER BY last_seen_at DESC")]
