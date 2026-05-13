"""
Exchange Rate Fetcher - 实时汇率获取模块

从网络获取最新汇率数据，支持多个API源切换。
"""

import httpx
from datetime import datetime
from typing import Optional, Dict, Any
from Sills.base import get_db_connection


def fetch_from_frankfurter() -> tuple[bool, Dict[str, Any]]:
    """
    从 Frankfurter API 获取汇率（欧洲央行数据，更新频繁）

    API格式: {"base":"CNY", "rates":{"USD":0.14725, "EUR":0.1257, ...}}
    表示: 1 CNY = X 外币

    返回:
        KRW/JPY: 1 CNY = X 外币
        USD/EUR: 1 币种 = X CNY (需要转换)
    """
    try:
        url = "https://api.frankfurter.app/latest?from=CNY&to=USD,EUR,KRW,JPY"
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, follow_redirects=True)
            response.raise_for_status()
            data = response.json()

            rates = data.get("rates", {})
            usd = rates.get("USD", 1)  # 1 CNY = X USD
            eur = rates.get("EUR", 1)  # 1 CNY = X EUR

            return True, {
                "krw": rates.get("KRW"),  # 1 CNY = X KRW
                "jpy": rates.get("JPY"),  # 1 CNY = X JPY
                "usd_to_rmb": round(1 / usd, 4) if usd else None,  # 1 USD = X CNY
                "eur_to_rmb": round(1 / eur, 4) if eur else None,  # 1 EUR = X CNY
                "base": "CNY",
                "source": "Frankfurter (ECB)",
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "date": data.get("date"),
                "raw_rates": rates
            }
    except Exception as e:
        return False, {"error": str(e), "source": "Frankfurter"}


def fetch_from_exchange_rate_api() -> tuple[bool, Dict[str, Any]]:
    """
    从 ExchangeRate-API 获取汇率（备用源）

    返回格式: 1 CNY = X 外币
    """
    try:
        url = "https://open.er-api.com/v6/latest/CNY"
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

            if data.get("result") != "success":
                return False, {"error": "API返回失败", "source": "ExchangeRate-API"}

            rates = data.get("rates", {})

            usd = rates.get("USD", 1)
            eur = rates.get("EUR", 1)

            return True, {
                "krw": rates.get("KRW"),
                "jpy": rates.get("JPY"),
                "usd_to_rmb": round(1 / usd, 4) if usd else None,
                "eur_to_rmb": round(1 / eur, 4) if eur else None,
                "base": "CNY",
                "source": "ExchangeRate-API",
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "raw_rates": rates
            }
    except Exception as e:
        return False, {"error": str(e), "source": "ExchangeRate-API"}


def fetch_exchange_rates_from_api() -> tuple[bool, Dict[str, Any]]:
    """
    从多个API源获取实时汇率（优先使用Frankfurter，数据更准确）

    返回:
        (success, result):
            success=True 时 result 包含汇率数据
            success=False 时 result 包含错误信息

    汇率含义:
        - KRW/JPY: 1 CNY = X 外币
        - USD/EUR: 1 币种 = X RMB
    """
    # 优先使用 Frankfurter API（欧洲央行数据，更新更频繁）
    success, result = fetch_from_frankfurter()
    if success and result.get("krw") and result.get("usd_to_rmb"):
        return success, result

    # 备用：ExchangeRate-API
    success, result = fetch_from_exchange_rate_api()
    if success and result.get("krw"):
        return success, result

    # 都失败
    return False, {"error": "所有汇率API均不可用", "source": "all"}


def save_exchange_rates_to_db(rates: Dict[str, Any]) -> tuple[bool, str]:
    """
    保存汇率到数据库（只更新固定4条记录，不插入新数据）

    Args:
        rates: 包含 krw, jpy, usd, eur 汇率数据

    Returns:
        (success, message)
    """
    try:
        raw_rates = rates.get("raw_rates", {})
        record_date = datetime.now().strftime("%Y-%m-%d")
        refresh_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 原始汇率：1 RMB = X 外币
        original_rates = {
            2: raw_rates.get("KRW"),   # KRW: currency_code=2 (ID=1)
            3: raw_rates.get("JPY"),   # JPY: currency_code=3 (ID=3)
            1: raw_rates.get("USD"),   # USD: currency_code=1 (ID=2)
            4: raw_rates.get("EUR"),   # EUR: currency_code=4 (ID=4)
        }

        with get_db_connection() as conn:
            for currency_code in [1, 2, 3, 4]:
                original = original_rates.get(currency_code)

                if original and original > 0:
                    # 获取该币种的比例
                    ratio_row = conn.execute(
                        "SELECT rate_ratio FROM uni_daily WHERE currency_code = ?",
                        (currency_code,)
                    ).fetchone()
                    rate_ratio = float(ratio_row[0]) if ratio_row and ratio_row[0] else 0.03

                    # 计算推荐汇率
                    if currency_code in [2, 3]:  # KRW, JPY: 1 RMB = X 外币
                        recommended = round(original * (1 + rate_ratio), 2)
                    else:  # USD, EUR: 1币种 = X RMB
                        recommended = round(1 / original * (1 - rate_ratio), 4)

                    # 只更新固定记录，不插入新数据
                    conn.execute(
                        """UPDATE uni_daily
                           SET exchange_rate=?, original_rate=?, last_refresh_time=?, record_date=?
                           WHERE currency_code=?""",
                        (recommended, original, refresh_time, record_date, currency_code)
                    )
            conn.commit()

        return True, "汇率已更新"
    except Exception as e:
        return False, str(e)


def get_realtime_rates_with_suggested() -> Dict[str, Any]:
    """
    获取实时汇率和建议汇率（使用数据库中的rate_ratio计算）

    Returns:
        exchange_rates: 推荐汇率（使用数据库比例计算）
        original_rates: 原始汇率（对比显示）
        rate_ratios: 数据库中的比例
    """
    success, result = fetch_exchange_rates_from_api()

    if not success:
        return {
            "success": False,
            "error": result.get("error"),
            "exchange_rates": None,
            "original_rates": None,
            "rate_ratios": None
        }

    # 原始汇率：1 RMB = X 外币
    original_rates = {
        "krw": result["krw"],
        "jpy": result["jpy"],
        "usd_to_rmb": result["usd_to_rmb"],  # 已经是 1 USD = X RMB
        "eur_to_rmb": result["eur_to_rmb"],  # 已经是 1 EUR = X RMB
    }

    # 从数据库获取比例
    rate_ratios = {"krw": 0.03, "jpy": 0.03, "usd": 0.03, "eur": 0.03}
    try:
        with get_db_connection() as conn:
            for currency_code, key in [(2, "krw"), (3, "jpy"), (1, "usd"), (4, "eur")]:
                row = conn.execute(
                    "SELECT rate_ratio FROM uni_daily WHERE currency_code = ? ORDER BY record_date DESC LIMIT 1",
                    (currency_code,)
                ).fetchone()
                if row and row[0]:
                    rate_ratios[key] = float(row[0])
    except:
        pass

    # 使用数据库比例计算推荐汇率
    exchange_rates = {
        "krw": round(result["krw"] * (1 + rate_ratios["krw"]), 2) if result["krw"] else None,
        "jpy": round(result["jpy"] * (1 + rate_ratios["jpy"]), 2) if result["jpy"] else None,
        "usd_to_rmb": round(result["usd_to_rmb"] * (1 - rate_ratios["usd"]), 4) if result["usd_to_rmb"] else None,
        "eur_to_rmb": round(result["eur_to_rmb"] * (1 - rate_ratios["eur"]), 4) if result["eur_to_rmb"] else None,
    }

    return {
        "success": True,
        "exchange_rates": exchange_rates,
        "original_rates": original_rates,
        "rate_ratios": rate_ratios,
        "update_time": result.get("update_time")
    }