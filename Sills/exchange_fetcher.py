"""
Exchange Rate Fetcher - 实时汇率获取模块

从网络获取最新汇率数据。
"""

import httpx
from datetime import datetime
from typing import Optional, Dict, Any
from Sills.base import get_db_connection


# ExchangeRate-API (免费，支持CNY基准)
EXCHANGE_RATE_API_URL = "https://open.er-api.com/v6/latest/CNY"


def fetch_exchange_rates_from_api() -> tuple[bool, Dict[str, Any]]:
    """
    从 ExchangeRate-API 获取实时汇率

    返回:
        (success, result):
            success=True 时 result 包含汇率数据
            success=False 时 result 包含错误信息

    汇率含义: 1 CNY = X 外币
    """
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(EXCHANGE_RATE_API_URL)
            response.raise_for_status()
            data = response.json()

            if data.get("result") != "success":
                return False, {"error": "API返回失败"}

            rates = data.get("rates", {})

            # 提取需要的币种
            return True, {
                "krw": rates.get("KRW"),
                "jpy": rates.get("JPY"),
                "usd_to_rmb": round(1 / rates.get("USD", 1), 4) if rates.get("USD") else None,
                "eur_to_rmb": round(1 / rates.get("EUR", 1), 4) if rates.get("EUR") else None,
                "base": "CNY",
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "raw_rates": rates
            }
    except httpx.TimeoutException:
        return False, {"error": "请求超时"}
    except httpx.HTTPError as e:
        return False, {"error": f"HTTP错误: {str(e)}"}
    except Exception as e:
        return False, {"error": str(e)}


def save_exchange_rates_to_db(rates: Dict[str, Any]) -> tuple[bool, str]:
    """
    保存汇率到数据库（使用数据库中的rate_ratio计算推荐汇率）

    Args:
        rates: 包含 krw, jpy, usd(原始USD汇率), eur(原始EUR汇率)

    Returns:
        (success, message)
    """
    try:
        raw_rates = rates.get("raw_rates", {})
        record_date = datetime.now().strftime("%Y-%m-%d")
        refresh_time = datetime.now().strftime("%Y-%m-%d %H:%M")

        # 原始汇率：1 RMB = X 外币
        original_rates = {
            2: raw_rates.get("KRW"),   # KRW: currency_code=2
            3: raw_rates.get("JPY"),   # JPY: currency_code=3
            1: raw_rates.get("USD"),   # USD: currency_code=1
            4: raw_rates.get("EUR"),   # EUR: currency_code=4
        }

        with get_db_connection() as conn:
            for currency_code in [1, 2, 3, 4]:
                original = original_rates.get(currency_code)

                if original and original > 0:
                    # 获取该币种的比例（如果存在）
                    ratio_row = conn.execute(
                        "SELECT rate_ratio FROM uni_daily WHERE currency_code = ? ORDER BY record_date DESC LIMIT 1",
                        (currency_code,)
                    ).fetchone()
                    rate_ratio = float(ratio_row[0]) if ratio_row and ratio_row[0] else 0.03

                    # 计算推荐汇率
                    if currency_code in [2, 3]:  # KRW, JPY: 1 RMB = X 外币
                        recommended = round(original * (1 + rate_ratio), 2)
                    else:  # USD, EUR: 1币种 = X RMB
                        recommended = round(1 / original * (1 - rate_ratio), 4)

                    # 检查今天是否已有记录
                    existing = conn.execute(
                        "SELECT id FROM uni_daily WHERE record_date=? AND currency_code=?",
                        (record_date, currency_code)
                    ).fetchone()

                    if existing:
                        # 更新今天的记录：exchange_rate=推荐汇率, original_rate=原始汇率
                        conn.execute(
                            "UPDATE uni_daily SET exchange_rate=?, original_rate=?, last_refresh_time=? WHERE id=?",
                            (recommended, original, refresh_time, existing[0])
                        )
                    else:
                        # 插入新记录
                        conn.execute(
                            "INSERT INTO uni_daily (record_date, currency_code, exchange_rate, original_rate, rate_ratio, last_refresh_time) VALUES (?, ?, ?, ?, ?, ?)",
                            (record_date, currency_code, recommended, original, rate_ratio, refresh_time)
                        )
            conn.commit()

        return True, "汇率已保存到数据库（推荐汇率）"
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