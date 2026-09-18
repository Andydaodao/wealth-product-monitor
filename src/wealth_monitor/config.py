import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.json"
CONFIG = {
    "web_host": "127.0.0.1",
    "web_port": 8765,
    "scan_interval_minutes": 720,
    "jitter_seconds": 60,
    "risk_levels": ["R1", "R2"],
    "preferred_holding_days_max": 90,
}
if CONFIG_PATH.exists():
    CONFIG.update(json.loads(CONFIG_PATH.read_text("utf-8")))
if CONFIG["scan_interval_minutes"] < 5:
    raise ValueError("监控间隔必须至少为 5 分钟")
