from wealth_monitor.monitor import parse_homepage, parse_notice_page, preference, upsert_product
from wealth_monitor import database
from wealth_monitor.app import app
from wealth_monitor.static_site import render_site, restore_state, save_state
from fastapi.testclient import TestClient


def test_parse_public_homepage_product():
    html = "<div>中银理财-稳富纯债7天持有期2号 CYQWFCZ7D2A 累计净值 1.014003</div>"
    products = list(parse_homepage(html))
    assert products == [{"name": "中银理财-稳富纯债7天持有期2号", "code": "CYQWFCZ7D2A", "days": 7}]


def test_preference_is_only_a_basic_filter():
    assert preference("中银理财-稳富纯债7天持有期2号", 7, "R2") == "符合基础偏好"
    assert preference("中银理财-稳富固收增强368天持有期", 368, "R2") == "需要进一步研究"


def test_parse_notice_open_date_without_inventing_a_time():
    html = '<a href="/notice/1.html">“中银理财-稳富（季增益）010”产品A份额开放预告（2026年9月28日开放）</a>'
    product = parse_notice_page(html)[0]
    assert product["name"] == "中银理财-稳富（季增益）010"
    assert product["date"] == "2026-09-28"
    assert "open_time" not in product


def test_sparse_refresh_preserves_disclosed_fields_and_deduplicates(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    product = {"code": "CYQWFCZ7D2A", "name": "中银理财-稳富纯债7天持有期2号", "days": 7, "risk": "R2"}
    assert upsert_product(product, "离线样例", "https://www.bocwm.cn/") is True
    assert upsert_product({k: v for k, v in product.items() if k != "risk"}, "离线样例", "https://www.bocwm.cn/") is False
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
        assert db.execute("SELECT risk_level FROM products").fetchone()[0] == "R2"


def test_unknown_risk_does_not_pass_risk_preference():
    assert preference("中银理财-稳富纯债7天持有期2号", 7, None) == "信息不足"


def test_watchlist_is_independent_from_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "watchlist.db")
    upsert_product({"code": "P1", "name": "测试在售产品", "risk": "R2"}, "离线样例", "https://example.com")
    client = TestClient(app)
    response = client.post("/products/1/watch", follow_redirects=False)
    assert response.status_code == 303
    with database.connect() as db:
        assert db.execute("SELECT status FROM products WHERE id=1").fetchone()[0] == "ACTIVE"
        assert db.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0] == 1
    assert "测试在售产品" in client.get("/?scope=WATCHLIST").text


def test_upcoming_without_disclosed_date_renders(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "undated.db")
    upsert_product({"code": "P2", "name": "日期待披露产品", "lifecycle_status": "UPCOMING"}, "离线样例", "https://example.com")
    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert "日期待披露" in response.text


def test_static_site_round_trip(monkeypatch, tmp_path):
    database_path = tmp_path / "first_run.db"
    state_path = tmp_path / "cloud_state.json"
    output_path = tmp_path / "public"
    monkeypatch.setattr(database, "DB_PATH", database_path)
    upsert_product(
        {"code": "P3", "name": "静态页面测试产品", "risk": "R2", "days": 30},
        "离线样例",
        "https://example.com",
    )
    save_state(state_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "next_run.db")
    restore_state(state_path)
    render_site(output_path)

    assert "静态页面测试产品" in (output_path / "index.html").read_text("utf-8")
    assert (output_path / "products" / "1.html").exists()
    assert (output_path / "static" / "app.css").exists()
