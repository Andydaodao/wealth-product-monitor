from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "wealth_monitor.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
 id INTEGER PRIMARY KEY, product_key TEXT UNIQUE NOT NULL, product_code TEXT,
 product_name TEXT NOT NULL, manager TEXT, risk_level TEXT, product_type TEXT,
 min_purchase_amount TEXT, min_holding_days INTEGER, benchmark_text TEXT,
 sale_start_date TEXT, sale_start_time TEXT, open_start_date TEXT, open_start_time TEXT,
 max_scale TEXT, status TEXT NOT NULL, preference_label TEXT NOT NULL,
 source_name TEXT NOT NULL, source_url TEXT NOT NULL,
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, product_key TEXT NOT NULL, event_type TEXT NOT NULL,
 summary TEXT NOT NULL, detected_at TEXT NOT NULL, source_url TEXT NOT NULL,
 fingerprint TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS source_runs (
 id INTEGER PRIMARY KEY, source_name TEXT NOT NULL, url TEXT NOT NULL,
 fetched_at TEXT NOT NULL, status TEXT NOT NULL, http_status INTEGER,
 item_count INTEGER NOT NULL DEFAULT 0, error_message TEXT
);
CREATE TABLE IF NOT EXISTS watchlist (
 product_key TEXT PRIMARY KEY,
 created_at TEXT NOT NULL,
 FOREIGN KEY(product_key) REFERENCES products(product_key) ON DELETE CASCADE
);
"""


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    db.execute("UPDATE products SET status='UPCOMING' WHERE status='即将开放'")
    db.execute("UPDATE products SET status='ACTIVE' WHERE status='持续运作'")
    db.commit()
    return db
