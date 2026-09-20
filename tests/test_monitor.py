import json

from wealth_monitor.monitor import (
    parse_homepage,
    parse_nav_index,
    parse_nav_page,
    parse_notice_page,
    preference,
    seed_public_snapshot,
    upsert_nav_rows,
    upsert_product,
)
from wealth_monitor.performance import calculate_performance
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
    html = '<a href="/html/1//198/197/1.html">“中银理财-稳富（季增益）010”产品A份额开放预告（2026年9月28日开放）</a>'
    product = parse_notice_page(html)[0]
    assert product["name"] == "中银理财-稳富（季增益）010"
    assert product["date"] == "2026-09-28"
    assert "open_time" not in product
    assert product["url"] == "https://www.bocwm.cn/html/1/198/197/1.html"


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


def test_public_snapshot_seeds_dated_nav_for_local_preview(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "snapshot.db")
    seed_public_snapshot()
    with database.connect() as db:
        row = db.execute(
            "SELECT nav_date,cumulative_nav FROM nav_history WHERE product_code='CYQWFCZ7D2A'"
        ).fetchone()
    assert tuple(row) == ("2026-09-14", "1.014003")


def test_parse_official_nav_index_and_history():
    index_html = '<a href="/sdbapp/wmpnetworth/7784/7788/13061/index_1719.html">中银理财-稳富7天-CYQWFZQHYLD7DA</a>'
    assert parse_nav_index(index_html) == {
        "CYQWFZQHYLD7DA": "https://www.bankofchina.com/sdbapp/wmpnetworth/7784/7788/13061/index_1719.html"
    }
    page_html = """
    <table><tr><th>产品代码</th><th>产品名称</th><th>份额净值</th><th>份额累计净值</th><th>发布日期</th></tr>
    <tr><td>CYQWFZQHYLD7DA</td><td>测试产品</td><td>1.0123</td><td>1.0456</td><td>2026-09-19</td></tr></table>
    <div>共2页</div>
    """
    rows, pages = parse_nav_page(page_html, "https://example.com/history.html")
    assert pages == 2
    assert rows == [{
        "product_code": "CYQWFZQHYLD7DA",
        "nav_date": "2026-09-19",
        "source_url": "https://example.com/history.html",
        "unit_nav": "1.0123",
        "cumulative_nav": "1.0456",
        "ten_thousand_income": None,
        "seven_day_annualized": None,
    }]


def test_calculate_public_nav_performance_uses_nearby_baselines():
    rows = [
        {"nav_date": "2026-01-01", "cumulative_nav": "1.0000", "unit_nav": "1.0000", "source_url": "https://example.com"},
        {"nav_date": "2026-03-20", "cumulative_nav": "1.0200", "unit_nav": "1.0200", "source_url": "https://example.com"},
        {"nav_date": "2026-06-19", "cumulative_nav": "1.0400", "unit_nav": "1.0400", "source_url": "https://example.com"},
        {"nav_date": "2026-08-20", "cumulative_nav": "1.0600", "unit_nav": "1.0600", "source_url": "https://example.com"},
        {"nav_date": "2026-09-19", "cumulative_nav": "1.0700", "unit_nav": "1.0700", "source_url": "https://example.com"},
    ]
    performance = calculate_performance(rows)
    assert performance["latest_nav"] == "1.0700"
    assert [period["return_text"] for period in performance["periods"]] == [
        "+0.94%", "+2.88%", "+4.90%", "+7.00%", "+7.00%"
    ]


def test_new_product_does_not_force_an_inception_return():
    performance = calculate_performance([
        {"nav_date": "2026-09-10", "cumulative_nav": "1.0000", "source_url": "https://example.com"},
        {"nav_date": "2026-09-19", "cumulative_nav": "1.0010", "source_url": "https://example.com"},
    ])
    assert all(period["return_text"] is None for period in performance["periods"])


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
    upsert_nav_rows([
        {"product_code": "P3", "nav_date": "2026-08-19", "unit_nav": "1.0000", "cumulative_nav": "1.0000", "ten_thousand_income": None, "seven_day_annualized": None, "source_url": "https://example.com/nav"},
        {"product_code": "P3", "nav_date": "2026-09-19", "unit_nav": "1.0100", "cumulative_nav": "1.0100", "ten_thousand_income": None, "seven_day_annualized": None, "source_url": "https://example.com/nav"},
    ])
    save_state(state_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "next_run.db")
    restore_state(state_path)
    render_site(output_path)

    assert "静态页面测试产品" in (output_path / "index.html").read_text("utf-8")
    assert (output_path / "products" / "1.html").exists()
    assert "公开净值表现" in (output_path / "products" / "1.html").read_text("utf-8")
    assert "+1.00%" in (output_path / "products" / "1.html").read_text("utf-8")
    assert (output_path / "static" / "app.css").exists()


def test_legacy_state_and_recent_scan_summary(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "scan-history.db")
    state_path = tmp_path / "legacy-state.json"
    state_path.write_text(json.dumps({
        "products": [],
        "events": [],
        "source_runs": [{
            "id": 1,
            "source_name": "历史来源",
            "url": "https://www.bocwm.cn/html/1//198/197/index.html",
            "fetched_at": "2026-09-19T01:00:00+08:00",
            "status": "正常",
            "http_status": 200,
            "item_count": 10,
            "error_message": None,
        }],
    }), "utf-8")
    restore_state(state_path)
    with database.connect() as db:
        db.executemany(
            "INSERT INTO source_runs(scan_id,source_name,url,fetched_at,status,item_count,new_count) "
            "VALUES(?,?,?,?,?,?,?)",
            [
                ("scan-1", "产品展示", "https://example.com/1", "2026-09-20T09:17:00+08:00", "正常", 9, 2),
                ("scan-1", "产品公告", "https://example.com/2", "2026-09-20T09:17:01+08:00", "异常", 0, 0),
            ],
        )

    output_path = tmp_path / "public"
    render_site(output_path)
    page = (output_path / "index.html").read_text("utf-8")
    assert "部分异常" in page
    assert "扫描 9 条 · 新增 2 条" in page
    with database.connect() as db:
        legacy = db.execute("SELECT scan_id,new_count,url FROM source_runs WHERE id=1").fetchone()
    assert legacy["scan_id"] is None
    assert legacy["new_count"] == 0
    assert legacy["url"] == "https://www.bocwm.cn/html/1/198/197/index.html"
