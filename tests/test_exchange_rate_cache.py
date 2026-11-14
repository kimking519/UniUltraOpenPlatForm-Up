import contextlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from Sills import base, db_daily, db_offer, exchange_fetcher


@pytest.fixture
def temp_db(monkeypatch):
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE uni_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_date TEXT,
            currency_code INTEGER,
            exchange_rate REAL,
            original_rate REAL,
            rate_ratio REAL,
            last_refresh_time TEXT
        );
        CREATE TABLE uni_offer (
            offer_id TEXT PRIMARY KEY,
            offer_price_rmb REAL,
            price_kwr REAL,
            price_usd REAL,
            price_jpy REAL
        );
    """)

    @contextlib.contextmanager
    def fake_get_db_connection():
        yield conn

    monkeypatch.setattr(base, "get_db_connection", fake_get_db_connection)
    monkeypatch.setattr(db_daily, "get_db_connection", fake_get_db_connection)
    monkeypatch.setattr(db_offer, "get_db_connection", fake_get_db_connection)
    monkeypatch.setattr(exchange_fetcher, "get_db_connection", fake_get_db_connection)
    base.clear_cache()

    yield conn

    base.clear_cache()
    conn.close()


def _seed_daily(conn):
    rows = [
        ("2026-01-01", 1, 6.551, 1 / 6.672, 0.018),
        ("2026-01-01", 2, 209.78, 204.64, 0.03),
        ("2026-01-01", 3, 24.16, 23.73, 0.018),
        ("2026-01-01", 4, 7.25, 1 / 7.3735, 0.018),
    ]
    conn.executemany("""
        INSERT INTO uni_daily
            (record_date, currency_code, exchange_rate, original_rate, rate_ratio)
        VALUES (?, ?, ?, ?, ?)
    """, rows)
    conn.commit()


def test_refresh_clears_all_cached_currency_rates(temp_db):
    _seed_daily(temp_db)
    assert base.get_exchange_rates() == (209.78, 6.551, 24.16)
    assert base.get_cached_rate(4) == 7.25

    ok, _ = exchange_fetcher.save_exchange_rates_to_db({
        "raw_rates": {
            "KRW": 200.41,
            "JPY": 23.981,
            "USD": 1 / 6.672,
            "EUR": 1 / 7.3735,
        }
    })

    assert ok is True
    assert base.get_exchange_rates() == (206.42, 6.5519, 24.41)
    assert base.get_cached_rate(4) == 7.2408


def test_manual_daily_changes_clear_cached_rate(temp_db):
    _seed_daily(temp_db)
    assert base.get_cached_rate(2) == 209.78

    ok, _ = db_daily.add_daily("2999-01-01", 2, 206.42)
    assert ok is True
    assert base.get_cached_rate(2) == 206.42

    rate_id = temp_db.execute(
        "SELECT id FROM uni_daily WHERE record_date = '2999-01-01'"
    ).fetchone()["id"]
    ok, _ = db_daily.update_daily(rate_id, 207.5)
    assert ok is True
    assert base.get_cached_rate(2) == 207.5


def test_ratio_updates_clear_cached_rate(temp_db, monkeypatch):
    _seed_daily(temp_db)
    assert base.get_cached_rate(2) == 209.78

    import main

    monkeypatch.setattr(main, "get_db_connection", base.get_db_connection)
    main.app.dependency_overrides[main.login_required] = lambda: {"rule": "3", "emp_id": "000"}
    client = TestClient(main.app)
    try:
        response = client.post("/api/exchange/update_ratio", json={
            "currency_code": 2,
            "rate_ratio": 0.05,
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert base.get_cached_rate(2) == 214.87

        rate_id = temp_db.execute(
            "SELECT id FROM uni_daily WHERE currency_code = 2"
        ).fetchone()["id"]
        response = client.post("/api/exchange/update_ratio_by_id", json={
            "id": rate_id,
            "rate_ratio": 0.01,
        })
        assert response.status_code == 200
        assert response.json()["success"] is True
        assert base.get_cached_rate(2) == 206.69
    finally:
        main.app.dependency_overrides.clear()


def test_rmb_update_recalculates_only_current_offer(temp_db, monkeypatch):
    temp_db.executemany("""
        INSERT INTO uni_offer
            (offer_id, offer_price_rmb, price_kwr, price_usd, price_jpy)
        VALUES (?, ?, ?, ?, ?)
    """, [
        ("O1", 10, 2097.8, 1.527, 241.6),
        ("O2", 20, 4195.6, 3.054, 483.2),
    ])
    temp_db.commit()
    monkeypatch.setattr(db_offer, "get_exchange_rates", lambda: (206.42, 6.5519, 24.41))

    ok, _ = db_offer.update_offer("O1", {"offer_price_rmb": 100})

    assert ok is True
    updated = temp_db.execute(
        "SELECT * FROM uni_offer WHERE offer_id = 'O1'"
    ).fetchone()
    assert updated["offer_price_rmb"] == 100
    assert updated["price_kwr"] == 20642.0
    assert updated["price_usd"] == 15.263
    assert updated["price_jpy"] == 2441.0

    untouched = temp_db.execute(
        "SELECT * FROM uni_offer WHERE offer_id = 'O2'"
    ).fetchone()
    assert dict(untouched) == {
        "offer_id": "O2",
        "offer_price_rmb": 20,
        "price_kwr": 4195.6,
        "price_usd": 3.054,
        "price_jpy": 483.2,
    }


def test_offer_update_api_uses_latest_adjusted_rates(temp_db, monkeypatch):
    _seed_daily(temp_db)
    temp_db.execute("""
        INSERT INTO uni_offer
            (offer_id, offer_price_rmb, price_kwr, price_usd, price_jpy)
        VALUES ('O1', 10, 2097.8, 1.527, 241.6)
    """)
    temp_db.executemany("""
        INSERT INTO uni_daily
            (record_date, currency_code, exchange_rate, original_rate, rate_ratio)
        VALUES ('2999-01-01', ?, ?, ?, ?)
    """, [
        (1, 6.5519, 1 / 6.672, 0.018),
        (2, 206.42, 200.41, 0.03),
        (3, 24.41, 23.981, 0.018),
    ])
    temp_db.commit()

    import main

    monkeypatch.setattr(main, "get_db_connection", base.get_db_connection)
    main.app.dependency_overrides[main.login_required] = lambda: {"rule": "3", "emp_id": "000"}
    client = TestClient(main.app)
    try:
        response = client.post("/api/offer/update", data={
            "offer_id": "O1",
            "field": "offer_price_rmb",
            "value": "100",
        })
        assert response.status_code == 200
        assert response.json()["prices"] == {
            "offer_price_rmb": 100.0,
            "price_kwr": 20642.0,
            "price_usd": 15.263,
            "price_jpy": 2441.0,
        }
    finally:
        main.app.dependency_overrides.clear()
