from fastapi import FastAPI, HTTPException

from mcp_server.schemas import CompareResponse, CoinMarketData, MarketSummaryResponse, OhlcResponse, TrendResponse, TrendingResponse
from mcp_server.services.coingecko_service import CoinGeckoError, CoinGeckoRateLimitError, CoinGeckoTimeoutError, get_coin_market_data, get_coin_ohlc, get_coin_trend, get_market_summary, get_trending_data

app = FastAPI(title="Crypto MCP Server", version="1.0.0")


def _rate_limit_detail() -> dict:
    return {
        "error": "rate_limited",
        "message": "Live market data is temporarily unavailable because the upstream crypto API is rate-limiting requests.",
        "retry_after_seconds": 60,
    }


def _timeout_detail() -> dict:
    return {
        "error": "upstream_timeout",
        "message": "Live market data is temporarily unavailable because the upstream crypto API is responding too slowly.",
        "retry_after_seconds": 15,
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/price", response_model=CoinMarketData)
def get_price(symbol: str):
    try:
        data = get_coin_market_data(symbol)
    except CoinGeckoRateLimitError as exc:
        raise HTTPException(status_code=503, detail=_rate_limit_detail()) from exc
    except CoinGeckoTimeoutError as exc:
        raise HTTPException(status_code=503, detail=_timeout_detail()) from exc
    except CoinGeckoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not data:
        raise HTTPException(status_code=404, detail=f"Coin '{symbol}' was not found")
    return data


@app.get("/compare", response_model=CompareResponse)
def compare(symbol1: str, symbol2: str):
    try:
        data1 = get_coin_market_data(symbol1)
        data2 = get_coin_market_data(symbol2)
    except CoinGeckoRateLimitError as exc:
        raise HTTPException(status_code=503, detail=_rate_limit_detail()) from exc
    except CoinGeckoTimeoutError as exc:
        raise HTTPException(status_code=503, detail=_timeout_detail()) from exc
    except CoinGeckoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not data1 or not data2:
        raise HTTPException(status_code=404, detail="One or both coins were not found")
    return {"coin_1": data1, "coin_2": data2}


@app.get("/trending", response_model=TrendingResponse)
def trending():
    try:
        return get_trending_data()
    except CoinGeckoRateLimitError as exc:
        raise HTTPException(status_code=503, detail=_rate_limit_detail()) from exc
    except CoinGeckoTimeoutError as exc:
        raise HTTPException(status_code=503, detail=_timeout_detail()) from exc
    except CoinGeckoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/market-summary", response_model=MarketSummaryResponse)
def market_summary():
    try:
        return get_market_summary()
    except CoinGeckoRateLimitError as exc:
        raise HTTPException(status_code=503, detail=_rate_limit_detail()) from exc
    except CoinGeckoTimeoutError as exc:
        raise HTTPException(status_code=503, detail=_timeout_detail()) from exc
    except CoinGeckoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/trend", response_model=TrendResponse)
def trend(symbol: str, days: int = 7):
    try:
        data = get_coin_trend(symbol, days=days)
    except CoinGeckoRateLimitError as exc:
        raise HTTPException(status_code=503, detail=_rate_limit_detail()) from exc
    except CoinGeckoTimeoutError as exc:
        raise HTTPException(status_code=503, detail=_timeout_detail()) from exc
    except CoinGeckoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not data:
        raise HTTPException(status_code=404, detail=f"Trend data for '{symbol}' was not found")
    return data


@app.get("/ohlc", response_model=OhlcResponse)
def ohlc(symbol: str, days: int = 7):
    try:
        data = get_coin_ohlc(symbol, days=days)
    except CoinGeckoRateLimitError as exc:
        raise HTTPException(status_code=503, detail=_rate_limit_detail()) from exc
    except CoinGeckoTimeoutError as exc:
        raise HTTPException(status_code=503, detail=_timeout_detail()) from exc
    except CoinGeckoError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not data:
        raise HTTPException(status_code=404, detail=f"OHLC data for '{symbol}' was not found")
    return data
