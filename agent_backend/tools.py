from __future__ import annotations

from difflib import get_close_matches
import json
import os

import requests
from cachetools import TTLCache, cached
from dotenv import load_dotenv

load_dotenv()


MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://localhost:8001")
MCP_TIMEOUT_SECONDS = 10

# Cache for MCP requests: 128 entries, 60 seconds TTL
_mcp_cache = TTLCache(maxsize=128, ttl=60)


class ToolExecutionError(Exception):
    pass


SYMBOL_ALIASES = {
    "btc": "btc",
    "bitcoin": "btc",
    "eth": "eth",
    "ethereum": "eth",
    "sol": "sol",
    "solana": "sol",
    "doge": "doge",
    "dogecoin": "doge",
    "xrp": "xrp",
    "ripple": "xrp",
    "ada": "ada",
    "cardano": "ada",
    "bnb": "bnb",
    "binance": "bnb",
    "binance coin": "bnb",
}


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_coin_price",
            "description": "Get the live market price, 24 hour move, and market cap for one crypto asset. (Crypto-only, not stocks)",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Crypto symbol or coin name, for example BTC, ETH, bitcoin, or solana.",
                    }
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_coins",
            "description": "Compare two crypto assets by price, market cap, and 24 hour change. (Crypto-only, not stocks)",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol1": {"type": "string"},
                    "symbol2": {"type": "string"},
                },
                "required": ["symbol1", "symbol2"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trending_coins",
            "description": "Get currently trending crypto assets. (Crypto-only, not stocks)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_summary",
            "description": "Get a quick market summary with top crypto coins, leaders, and laggards. (Crypto-only, not stocks)",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_coin_trend",
            "description": "Get a recent normalized price trend for one crypto asset, useful for dashboards and exploratory analysis. (Crypto-only, not stocks)",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string"},
                    "days": {"type": "integer", "default": 7},
                },
                "required": ["symbol"],
            },
        },
    },
]


def normalize_symbol(symbol_or_name: str) -> str:
    value = symbol_or_name.strip().lower()
    if not value:
        return symbol_or_name

    alias = SYMBOL_ALIASES.get(value)
    if alias:
        return alias

    match = get_close_matches(value, SYMBOL_ALIASES.keys(), n=1, cutoff=0.8)
    if match:
        return SYMBOL_ALIASES[match[0]]
    return value



# Helper to make params hashable for caching
def _make_hashable_params(params):
    if params is None:
        return None
    return tuple(sorted(params.items()))

@cached(_mcp_cache, key=lambda path, params=None: (path, _make_hashable_params(params)))
def _request(path: str, *, params: dict | None = None) -> dict:
    try:
        response = requests.get(f"{MCP_BASE_URL}{path}", params=params, timeout=MCP_TIMEOUT_SECONDS)
    except requests.Timeout as exc:
        raise ToolExecutionError("Live market data is temporarily unavailable because the internal market-data service timed out.") from exc
    except requests.RequestException as exc:
        raise ToolExecutionError("Live market data is temporarily unavailable because the internal market-data service could not be reached.") from exc
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        detail = payload.get("detail", response.text[:250])
        if isinstance(detail, dict) and detail.get("error") in {"rate_limited", "upstream_timeout"}:
            raise ToolExecutionError(detail.get("message", "Live market data is temporarily unavailable.")) from exc
        raise ToolExecutionError(f"Tool call failed for {path}: {detail}") from exc
    return response.json()


def call_tool(tool_name: str, arguments: dict) -> dict:
    if tool_name == "get_coin_price":
        symbol = normalize_symbol(arguments["symbol"])
        return _request("/price", params={"symbol": symbol})
    if tool_name == "compare_coins":
        symbol1 = normalize_symbol(arguments["symbol1"])
        symbol2 = normalize_symbol(arguments["symbol2"])
        return _request(
            "/compare",
            params={"symbol1": symbol1, "symbol2": symbol2},
        )
    if tool_name == "get_trending_coins":
        return _request("/trending")
    if tool_name == "get_market_summary":
        return _request("/market-summary")
    if tool_name == "get_coin_trend":
        symbol = normalize_symbol(arguments["symbol"])
        days = int(arguments.get("days", 7))
        return _request("/trend", params={"symbol": symbol, "days": days})
    raise ToolExecutionError(f"Unsupported tool: {tool_name}")


def normalize_tool_arguments(tool_name: str, arguments: dict) -> dict:
    normalized = dict(arguments)
    if tool_name == "get_coin_price" and "symbol" in normalized:
        normalized["symbol"] = normalize_symbol(normalized["symbol"])
    if tool_name == "compare_coins":
        if "symbol1" in normalized:
            normalized["symbol1"] = normalize_symbol(normalized["symbol1"])
        if "symbol2" in normalized:
            normalized["symbol2"] = normalize_symbol(normalized["symbol2"])
    if tool_name == "get_coin_trend" and "symbol" in normalized:
        normalized["symbol"] = normalize_symbol(normalized["symbol"])
    return normalized


def parse_tool_arguments(raw_arguments: str | None) -> dict:
    if not raw_arguments:
        return {}
    return json.loads(raw_arguments)
