from pydantic import BaseModel, Field


class CoinMarketData(BaseModel):
    symbol: str
    name: str
    price_usd: float
    change_24h: float | None = None
    market_cap: float | None = None
    total_volume: float | None = None
    market_cap_rank: int | None = None
    sparkline_7d: list[float] = Field(default_factory=list)


class CompareResponse(BaseModel):
    coin_1: CoinMarketData
    coin_2: CoinMarketData


class TrendingCoin(BaseModel):
    name: str
    symbol: str
    market_cap_rank: int | None = None


class TrendingResponse(BaseModel):
    coins: list[TrendingCoin]


class MarketSummaryResponse(BaseModel):
    top_coins: list[CoinMarketData] = Field(default_factory=list)
    leaders: list[CoinMarketData] = Field(default_factory=list)
    laggards: list[CoinMarketData] = Field(default_factory=list)
    total_market_cap: float | None = None
    total_volume_24h: float | None = None


class TrendPoint(BaseModel):
    timestamp: int
    price_usd: float


class TrendResponse(BaseModel):
    symbol: str
    name: str
    days: int
    points: list[TrendPoint] = Field(default_factory=list)


class OhlcPoint(BaseModel):
    timestamp: int
    open_usd: float
    high_usd: float
    low_usd: float
    close_usd: float


class OhlcResponse(BaseModel):
    symbol: str
    name: str
    days: int
    candles: list[OhlcPoint] = Field(default_factory=list)
