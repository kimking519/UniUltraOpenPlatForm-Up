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
    保存汇率到数据库

    Args:
        rates: 包含 krw, jpy, usd(原始USD汇率), eur(原始EUR汇率)

    Returns:
        (success, message)
    """
    try:
        raw_rates = rates.get("raw_rates", {})
        record_date = datetime.now().strftime("%Y-%m-%d")

        # 汇率数据：存储的是 1 RMB = X 外币
        rate_data = {
            2: raw_rates.get("KRW"),   # KRW: currency_code=2
            3: raw_rates.get("JPY"),   # JPY: currency_code=3
            1: raw_rates.get("USD"),   # USD: currency_code=1
            4: raw_rates.get("EUR"),   # EUR: currency_code=4
        }

        with get_db_connection() as conn:
            for currency_code, rate in rate_data.items():
                if rate and rate > 0:
                    # 检查今天是否已有记录
                    existing = conn.execute(
                        "SELECT id FROM uni_daily WHERE record_date=? AND currency_code=?",
                        (record_date, currency_code)
                    ).fetchone()

                    if existing:
                        # 更新今天的记录
                        conn.execute(
                            "UPDATE uni_daily SET exchange_rate=? WHERE id=?",
                            (rate, existing[0])
                        )
                    else:
                        # 插入新记录
                        conn.execute(
                            "INSERT INTO uni_daily (record_date, currency_code, exchange_rate) VALUES (?, ?, ?)",
                            (record_date, currency_code, rate)
                        )
            conn.commit()

        return True, "汇率已保存到数据库"
    except Exception as e:
        return False, str(e)


def get_realtime_rates_with_suggested() -> Dict[str, Any]:
    """
    获取实时汇率和建议汇率

    Returns:
        包含实时汇率和建议汇率的字典
    """
    success, result = fetch_exchange_rates_from_api()

    if not success:
        return {
            "success": False,
            "error": result.get("error"),
            "exchange_rates": None,
            "suggested_rates": None
        }

    # 计算建议汇率
    suggested_rates = {
        "krw": round(result["krw"] * 1.025, 2) if result["krw"] else None,
        "jpy": round(result["jpy"] * 1.025, 2) if result["jpy"] else None,
        "usd_to_rmb": round(result["usd_to_rmb"] * 0.975, 4) if result["usd_to_rmb"] else None,
        "eur_to_rmb": round(result["eur_to_rmb"] * 0.975, 4) if result["eur_to_rmb"] else None,
    }

    return {
        "success": True,
        "exchange_rates": result,
        "suggested_rates": suggested_rates,
        "update_time": result.get("update_time")
    }