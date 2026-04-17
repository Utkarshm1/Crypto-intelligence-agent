from __future__ import annotations

from difflib import SequenceMatcher
import time

import requests

BASE_URL = "https://api.coingecko.com/api/v3"
CACHE_TTL_SECONDS = 60
UPSTREAM_TIMEOUT_SECONDS = 8

SYMBOL_ALIASES = {
    "btc": "bitcoin",
    "bitcoin": "bitcoin",
    "eth": "ethereum",
    "ethereum": "ethereum",
    "sol": "solana",
    "solana": "solana",
    "doge": "dogecoin",
    "dogecoin": "dogecoin",
    "xrp": "ripple",
    "ripple": "ripple",
    "ada": "cardano",
    "cardano": "cardano",
    "bnb": "binancecoin",
}


class CoinGeckoError(Exception):
    pass


class CoinGeckoRateLimitError(CoinGeckoError):
    pass


class CoinGeckoTimeoutError(CoinGeckoError):
    pass


_CACHE: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, dict | list]] = {}


def _cache_key(path: str, params: dict | None) -> tuple[str, tuple[tuple[str, str], ...]]:
    normalized_params = tuple(sorted((params or {}).items()))
    return (path, tuple((str(key), str(value)) for key, value in normalized_params))


def _get_cached(path: str, params: dict | None) -> dict | list | None:
    key = _cache_key(path, params)
    cached = _CACHE.get(key)
    if not cached:
        return None
    cached_at, payload = cached
    if time.time() - cached_at > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return payload


def _set_cached(path: str, params: dict | None, payload: dict | list) -> None:
    _CACHE[_cache_key(path, params)] = (time.time(), payload)


def _get(path: str, *, params: dict | None = None) -> dict | list:
    cached = _get_cached(path, params)
    if cached is not None:
        return cached

    try:
        response = requests.get(f"{BASE_URL}{path}", params=params, timeout=UPSTREAM_TIMEOUT_SECONDS)
    except requests.Timeout as exc:
        raise CoinGeckoTimeoutError("Live market data is temporarily unavailable because the upstream crypto API timed out.") from exc
    except requests.RequestException as exc:
        raise CoinGeckoError("CoinGecko request failed before a response was received.") from exc
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        if response.status_code == 429:
            raise CoinGeckoRateLimitError("Live market data is temporarily rate-limited upstream.") from exc
        detail = response.text[:200]
        raise CoinGeckoError(f"CoinGecko request failed: {detail}") from exc
    payload = response.json()
    _set_cached(path, params, payload)
    return payload


def _normalize_market_coin(coin: dict) -> dict:
    return {
        "symbol": str(coin.get("symbol", "")).upper(),
        "name": coin.get("name", "Unknown"),
        "price_usd": float(coin.get("current_price", 0)),
        "change_24h": coin.get("price_change_percentage_24h"),
        "market_cap": coin.get("market_cap"),
        "total_volume": coin.get("total_volume"),
        "market_cap_rank": coin.get("market_cap_rank"),
        "sparkline_7d": coin.get("sparkline_in_7d", {}).get("price", []) if coin.get("sparkline_in_7d") else [],
    }


def resolve_coin_id(symbol_or_name: str) -> str | None:
    query = symbol_or_name.strip().lower()
    if not query:
        return None

    alias = SYMBOL_ALIASES.get(query)
    if alias:
        return alias

    results = _get("/search", params={"query": query})
    coins = results.get("coins", []) if isinstance(results, dict) else []
    if not coins:
        return None

    best_match = max(
        coins,
        key=lambda item: max(
            SequenceMatcher(None, query, str(item.get("symbol", "")).lower()).ratio(),
            SequenceMatcher(None, query, str(item.get("name", "")).lower()).ratio(),
        ),
    )
    return best_match.get("id")


def get_coin_market_data(symbol_or_name: str) -> dict | None:
    coin_id = resolve_coin_id(symbol_or_name)
    if not coin_id:
        return None

    data = _get(
        "/coins/markets",
        params={
            "vs_currency": "usd",
            "ids": coin_id,
            "price_change_percentage": "24h",
            "sparkline": "true",
        },
    )
    if not data:
        return None
    return _normalize_market_coin(data[0])


def get_trending_data() -> dict:
    payload = _get("/search/trending")
    items = payload.get("coins", []) if isinstance(payload, dict) else []
    return {
        "coins": [
            {
                "name": item["item"]["name"],
                "symbol": item["item"]["symbol"].upper(),
                "market_cap_rank": item["item"].get("market_cap_rank"),
            }
            for item in items
        ]
    }


def get_market_summary() -> dict:
    data = _get(
        "/coins/markets",
        params={
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 15,
            "page": 1,
            "sparkline": "true",
            "price_change_percentage": "24h",
        },
    )
    normalized = [_normalize_market_coin(coin) for coin in data]
    movers = sorted(
        normalized,
        key=lambda coin: coin["change_24h"] if coin["change_24h"] is not None else float("-inf"),
        reverse=True,
    )
    laggards = sorted(
        normalized,
        key=lambda coin: coin["change_24h"] if coin["change_24h"] is not None else float("inf"),
    )
    return {
        "top_coins": normalized[:5],
        "leaders": movers[:3],
        "laggards": laggards[:3],
        "total_market_cap": sum(coin.get("market_cap") or 0 for coin in normalized[:10]),
        "total_volume_24h": sum(coin.get("total_volume") or 0 for coin in normalized[:10]),
    }


def get_coin_trend(symbol_or_name: str, *, days: int = 7) -> dict | None:
    coin_id = resolve_coin_id(symbol_or_name)
    if not coin_id:
        return None

    coin_data = get_coin_market_data(symbol_or_name)
    if not coin_data:
        return None

    payload = _get(
        f"/coins/{coin_id}/market_chart",
        params={"vs_currency": "usd", "days": days, "interval": "daily"},
    )
    prices = payload.get("prices", []) if isinstance(payload, dict) else []
    return {
        "symbol": coin_data["symbol"],
        "name": coin_data["name"],
        "days": days,
        "points": [{"timestamp": int(point[0]), "price_usd": float(point[1])} for point in prices],
    }


def get_coin_ohlc(symbol_or_name: str, *, days: int = 7) -> dict | None:
    coin_id = resolve_coin_id(symbol_or_name)
    if not coin_id:
        return None

    coin_data = get_coin_market_data(symbol_or_name)
    if not coin_data:
        return None

    payload = _get(
        f"/coins/{coin_id}/ohlc",
        params={"vs_currency": "usd", "days": days},
    )
    if not isinstance(payload, list):
        return None

    return {
        "symbol": coin_data["symbol"],
        "name": coin_data["name"],
        "days": days,
        "candles": [
            {
                "timestamp": int(point[0]),
                "open_usd": float(point[1]),
                "high_usd": float(point[2]),
                "low_usd": float(point[3]),
                "close_usd": float(point[4]),
            }
            for point in payload
        ],
    }
