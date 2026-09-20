from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, InvalidOperation


def _decimal(value: str | None) -> Decimal | None:
    try:
        return Decimal(value) if value not in (None, "") else None
    except InvalidOperation:
        return None


def _percent(value: Decimal) -> str:
    return f"{value * 100:+.2f}%"


def calculate_performance(rows: list[dict]) -> dict | None:
    observations = []
    for row in rows:
        try:
            nav_date = date.fromisoformat(row["nav_date"])
        except (KeyError, TypeError, ValueError):
            continue
        value = _decimal(row.get("cumulative_nav")) or _decimal(row.get("unit_nav"))
        observations.append({**row, "date": nav_date, "value": value})
    observations.sort(key=lambda row: row["date"])
    if not observations:
        return None

    latest = observations[-1]
    result = {
        "latest_date": latest["nav_date"],
        "latest_nav": str(latest["value"]) if latest["value"] is not None else None,
        "ten_thousand_income": latest.get("ten_thousand_income"),
        "seven_day_annualized": latest.get("seven_day_annualized"),
        "history_count": len(observations),
        "history_start": observations[0]["nav_date"],
        "source_url": latest["source_url"],
        "periods": [],
    }
    if latest.get("ten_thousand_income") is not None or latest.get("seven_day_annualized") is not None:
        result["kind"] = "cash"
        return result

    result["kind"] = "nav"
    if latest["value"] is None or latest["value"] <= 0:
        return result

    targets = (
        ("近1月", latest["date"] - timedelta(days=30)),
        ("近3月", latest["date"] - timedelta(days=91)),
        ("近6月", latest["date"] - timedelta(days=182)),
        ("今年以来", date(latest["date"].year, 1, 1)),
    )
    valued = [row for row in observations if row["value"] is not None and row["value"] > 0]
    for label, target in targets:
        candidates = [row for row in valued if row["date"] <= target]
        base = candidates[-1] if candidates else None
        if base is None or target - base["date"] > timedelta(days=10):
            result["periods"].append({"label": label, "return_text": None, "base_date": None})
            continue
        change = latest["value"] / base["value"] - Decimal("1")
        result["periods"].append({
            "label": label,
            "return_text": _percent(change),
            "base_date": base["nav_date"],
        })

    first = valued[0] if valued else None
    inception_text = None
    if (
        first
        and len(valued) >= 3
        and latest["date"] - first["date"] >= timedelta(days=7)
    ):
        inception_text = _percent(latest["value"] / first["value"] - Decimal("1"))
    result["periods"].append({
        "label": "成立以来",
        "return_text": inception_text,
        "base_date": first["nav_date"] if inception_text else None,
    })
    return result
