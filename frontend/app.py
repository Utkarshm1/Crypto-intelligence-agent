from __future__ import annotations

import os
from datetime import datetime

import altair as alt
import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.getenv("AGENT_BACKEND_URL", "http://localhost:8000")
MCP_URL = os.getenv("MCP_BASE_URL", "http://localhost:8001")
DEFAULT_COMPARE_1 = "btc"
DEFAULT_COMPARE_2 = "eth"
COIN_OPTIONS = ["btc", "eth", "sol", "xrp", "bnb", "ada", "doge"]
EXAMPLE_PROMPTS = [
    "What is the current price of BTC?",
    "Compare BTC and ETH today",
    "Which coin is doing better today, BTC or ETH?",
    "What should I look at in the market right now?",
]


def format_currency(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.6f}"


def format_change(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def summarize_result(result: dict) -> str:
    if not isinstance(result, dict):
        return "Returned non-object data."
    if result.get("error"):
        return "Data unavailable."
    if "price_usd" in result:
        return f"{result.get('name', 'Asset')} at {format_currency(result.get('price_usd'))} with 24h change {format_change(result.get('change_24h'))}."
    if "coin_1" in result and "coin_2" in result:
        coin_1 = result["coin_1"]
        coin_2 = result["coin_2"]
        return f"Compared {coin_1.get('symbol')} and {coin_2.get('symbol')} on price, 24h change, and market cap."
    if "coins" in result:
        return f"Returned {len(result.get('coins', []))} assets."
    if "candles" in result:
        return f"Returned {len(result.get('candles', []))} candlesticks."
    if "leaders" in result:
        return "Returned market leaders, laggards, and top coins."
    if "points" in result:
        return f"Returned {len(result.get('points', []))} trend points."
    return "Returned normalized market data."


def render_trace(trace: list[dict]) -> None:
    st.markdown("**Execution Trace**")
    for index, step in enumerate(trace, start=1):
        label = f"{index}. {step.get('tool', 'unknown tool')}"
        with st.expander(label):
            st.markdown(f"**Why**: {step.get('reason', 'No reason recorded.')}")
            st.markdown("**Input**")
            st.json(step.get("arguments", {}))
            st.markdown(f"**Summary**: {summarize_result(step.get('result', {}))}")
            st.markdown("**Data Retrieved**")
            st.json(step.get("result", {}))


def extract_error_message(payload: dict | None, fallback: str) -> str:
    if not isinstance(payload, dict):
        return fallback
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return detail.get("message", fallback)
    if isinstance(detail, str):
        return detail
    if isinstance(payload.get("error"), str):
        return payload["error"]
    return fallback


def fetch_json(path: str, *, params: dict | None = None) -> dict:
    try:
        response = requests.get(f"{MCP_URL}{path}", params=params, timeout=30)
        payload = response.json()
    except requests.Timeout:
        return {"error": "The dashboard request timed out while waiting for live market data."}
    except ValueError:
        payload = {}
    except requests.RequestException:
        return {"error": "The dashboard could not reach the live market-data service."}
    if not response.ok:
        return {
            "error": extract_error_message(
                payload,
                "The dashboard could not load live market data.",
            )
        }
    return payload


@st.cache_data(ttl=90, show_spinner=False)
def load_market_summary() -> dict | None:
    return fetch_json("/market-summary")


@st.cache_data(ttl=90, show_spinner=False)
def load_trending() -> dict | None:
    return fetch_json("/trending")


@st.cache_data(ttl=90, show_spinner=False)
def load_compare(symbol1: str, symbol2: str) -> dict | None:
    return fetch_json("/compare", params={"symbol1": symbol1, "symbol2": symbol2})


@st.cache_data(ttl=90, show_spinner=False)
def load_ohlc(symbol: str, days: int = 7) -> dict | None:
    return fetch_json("/ohlc", params={"symbol": symbol, "days": days})


def build_ohlc_rows(candles: list[dict]) -> list[dict]:
    rows = []
    for candle in candles:
        body_low = min(candle["open_usd"], candle["close_usd"])
        body_high = max(candle["open_usd"], candle["close_usd"])
        rows.append(
            {
                "time": datetime.fromtimestamp(candle["timestamp"] / 1000),
                "open_usd": candle["open_usd"],
                "high_usd": candle["high_usd"],
                "low_usd": candle["low_usd"],
                "close_usd": candle["close_usd"],
                "body_low": body_low,
                "body_high": body_high,
                "direction": "Up" if candle["close_usd"] >= candle["open_usd"] else "Down",
                "date_label": datetime.fromtimestamp(candle["timestamp"] / 1000).strftime("%b %d %H:%M"),
            }
        )
    return rows


def compress_ohlc_rows(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    frame["day"] = frame["time"].dt.strftime("%b %d")
    grouped = (
        frame.sort_values("time")
        .groupby("day", sort=False)
        .agg(
            time=("time", "first"),
            open_usd=("open_usd", "first"),
            high_usd=("high_usd", "max"),
            low_usd=("low_usd", "min"),
            close_usd=("close_usd", "last"),
        )
        .reset_index()
    )
    grouped["body_low"] = grouped[["open_usd", "close_usd"]].min(axis=1)
    grouped["body_high"] = grouped[["open_usd", "close_usd"]].max(axis=1)
    grouped["direction"] = grouped.apply(
        lambda row: "Up" if row["close_usd"] >= row["open_usd"] else "Down",
        axis=1,
    )
    grouped["date_label"] = grouped["day"]
    return grouped


def render_candlestick_chart(candles: list[dict], *, height: int = 260) -> None:
    rows = build_ohlc_rows(candles)
    if not rows:
        st.info("Candlestick data is unavailable for this selection.")
        return

    chart_data = compress_ohlc_rows(rows)
    min_price = float(chart_data["low_usd"].min())
    max_price = float(chart_data["high_usd"].max())
    price_padding = max((max_price - min_price) * 0.08, max_price * 0.005)
    y_scale = alt.Scale(domain=[min_price - price_padding, max_price + price_padding], zero=False)
    rule = (
        alt.Chart(chart_data)
        .mark_rule()
        .encode(
            x=alt.X("date_label:O", title="Time", sort=None),
            y=alt.Y("low_usd:Q", title="Price (USD)", scale=y_scale),
            y2="high_usd:Q",
            color=alt.Color(
                "direction:N",
                scale=alt.Scale(domain=["Up", "Down"], range=["#34d399", "#fb7185"]),
                legend=None,
            ),
        )
    )
    bar = (
        alt.Chart(chart_data)
        .mark_bar(size=10)
        .encode(
            x=alt.X("date_label:O", title="Time", sort=None),
            y=alt.Y("body_low:Q", title="Price (USD)", scale=y_scale),
            y2="body_high:Q",
            color=alt.Color(
                "direction:N",
                scale=alt.Scale(domain=["Up", "Down"], range=["#34d399", "#fb7185"]),
                legend=None,
            ),
            tooltip=[
                alt.Tooltip("date_label:O", title="Time"),
                alt.Tooltip("open_usd:Q", title="Open", format=",.2f"),
                alt.Tooltip("high_usd:Q", title="High", format=",.2f"),
                alt.Tooltip("low_usd:Q", title="Low", format=",.2f"),
                alt.Tooltip("close_usd:Q", title="Close", format=",.2f"),
            ],
        )
    )
    chart = (rule + bar).properties(height=height)
    st.altair_chart(chart, use_container_width=True)


def render_coin_snapshot(container, coin: dict, title: str) -> None:
    with container:
        st.markdown(f"**{title}**")
        st.metric(f"{coin['name']} ({coin['symbol']})", format_currency(coin.get("price_usd")), format_change(coin.get("change_24h")))
        st.caption(
            f"Market cap: {format_currency(coin.get('market_cap'))} | Volume: {format_currency(coin.get('total_volume'))}"
        )


def render_dashboard() -> None:
    st.subheader("Market Dashboard")
    summary = load_market_summary()
    trending = load_trending()

    if summary.get("error"):
        st.warning(summary["error"])
        st.caption("The chat flow can still work if the agent backend is available.")
        return

    top_left, top_mid, top_right = st.columns(3)
    with top_left:
        st.metric("Tracked Market Cap", format_currency(summary.get("total_market_cap")))
    with top_mid:
        st.metric("Tracked 24h Volume", format_currency(summary.get("total_volume_24h")))
    with top_right:
        leader = summary.get("leaders", [{}])[0]
        st.metric("Top Performer", leader.get("symbol", "n/a"), format_change(leader.get("change_24h")))

    mover_col, trend_col = st.columns([1.15, 1])

    with mover_col:
        st.markdown("**Top-Performing Assets**")
        leaders = summary.get("leaders", [])
        if leaders:
            table_rows = [
                {
                    "Asset": f"{coin['name']} ({coin['symbol']})",
                    "Price": format_currency(coin.get("price_usd")),
                    "24h": format_change(coin.get("change_24h")),
                    "Market Cap": format_currency(coin.get("market_cap")),
                }
                for coin in leaders
            ]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)

        st.markdown("**Trending Assets**")
        trending_coins = trending.get("coins", []) if trending and not trending.get("error") else []
        if trending_coins:
            st.dataframe(
                [
                    {
                        "Asset": f"{coin['name']} ({coin['symbol']})",
                        "Rank": coin.get("market_cap_rank"),
                    }
                    for coin in trending_coins[:7]
                ],
                use_container_width=True,
                hide_index=True,
            )
        elif trending and trending.get("error"):
            st.caption(trending["error"])

    with trend_col:
        st.markdown("**7-Day Trend View**")
        trend_symbol = st.selectbox("Trend asset", COIN_OPTIONS, index=0, key="trend_symbol")
        ohlc_data = load_ohlc(trend_symbol, days=7)
        if ohlc_data.get("candles"):
            render_candlestick_chart(ohlc_data["candles"], height=260)
            st.caption(f"{ohlc_data['name']} ({ohlc_data['symbol']}) candlestick view over the last {ohlc_data['days']} days")
        elif ohlc_data.get("error"):
            st.info(ohlc_data["error"])
        else:
            st.info("Candlestick data is unavailable for the selected asset.")

    st.markdown("**Comparison View**")
    compare_left, compare_right = st.columns(2)
    with compare_left:
        symbol1 = st.selectbox("First asset", COIN_OPTIONS, index=COIN_OPTIONS.index(DEFAULT_COMPARE_1), key="compare_symbol1")
    with compare_right:
        symbol2 = st.selectbox("Second asset", COIN_OPTIONS, index=COIN_OPTIONS.index(DEFAULT_COMPARE_2), key="compare_symbol2")

    compare_data = load_compare(symbol1, symbol2)
    if compare_data.get("coin_1") and compare_data.get("coin_2"):
        col_1, col_2 = st.columns(2)
        render_coin_snapshot(col_1, compare_data["coin_1"], "Asset One")
        render_coin_snapshot(col_2, compare_data["coin_2"], "Asset Two")

        trend_col_1, trend_col_2 = st.columns(2)
        trend_1 = load_ohlc(symbol1, days=7)
        trend_2 = load_ohlc(symbol2, days=7)
        with trend_col_1:
            if trend_1 and trend_1.get("candles"):
                render_candlestick_chart(trend_1["candles"], height=220)
            elif trend_1.get("error"):
                st.caption(trend_1["error"])
        with trend_col_2:
            if trend_2 and trend_2.get("candles"):
                render_candlestick_chart(trend_2["candles"], height=220)
            elif trend_2.get("error"):
                st.caption(trend_2["error"])
    elif compare_data.get("error"):
        st.info(compare_data["error"])


def handle_prompt_submission(prompt: str) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Running tools and drafting market insights..."):
            try:
                response = requests.post(
                    f"{BACKEND_URL}/chat",
                    json={"message": prompt},
                    timeout=90,
                )
                response.raise_for_status()
                payload = response.json()
                answer = payload["response"]
                trace = payload.get("trace", [])
                st.markdown(answer)
                if trace:
                    render_trace(trace)
                st.caption(f"Model: {payload.get('model', 'unknown')}")
                st.session_state.messages.append({"role": "assistant", "content": answer, "trace": trace})
            except requests.HTTPError:
                error_payload = response.json() if response.content else {}
                detail = error_payload.get("detail", "Backend request failed.")
                st.error(detail)
                st.session_state.messages.append({"role": "assistant", "content": detail})
            except requests.RequestException as exc:
                detail = f"Could not reach the backend: {exc}"
                st.error(detail)
                st.session_state.messages.append({"role": "assistant", "content": detail})


st.set_page_config(page_title="Crypto Intelligence Agent", page_icon="C", layout="wide")

st.markdown(
    """
    <style>
    .stApp {
        background:
            radial-gradient(circle at top left, rgba(41, 98, 255, 0.18), transparent 30%),
            radial-gradient(circle at top right, rgba(16, 185, 129, 0.18), transparent 25%),
            linear-gradient(180deg, #081120 0%, #0d172a 100%);
        color: #e5eefc;
    }
    .hero {
        padding: 1.2rem 1.4rem;
        border: 1px solid rgba(148, 163, 184, 0.2);
        border-radius: 20px;
        background: rgba(8, 15, 31, 0.72);
        backdrop-filter: blur(10px);
        margin-bottom: 1rem;
    }
    .hero h1 {
        margin: 0;
        font-size: 2rem;
    }
    .hero p {
        margin: 0.35rem 0 0;
        color: #bfd0ea;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <h1>Crypto Intelligence Agent</h1>
        <p>Decision-support for live crypto research with tool-grounded chat and a lightweight market dashboard.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("Try prompts")
    for index, example_prompt in enumerate(EXAMPLE_PROMPTS):
        if st.button(example_prompt, key=f"example_prompt_{index}", use_container_width=True):
            st.session_state["queued_prompt"] = example_prompt
    if st.button("Refresh dashboard data", use_container_width=True):
        load_market_summary.clear()
        load_trending.clear()
        load_compare.clear()
        load_ohlc.clear()

if "messages" not in st.session_state:
    st.session_state.messages = []

dashboard_tab, chat_tab = st.tabs(["Dashboard", "Agent Chat"])

with dashboard_tab:
    render_dashboard()

with chat_tab:
    st.subheader("Ask the Agent")
    st.caption("Use one of the example prompts in the sidebar or type your own question below.")
    quick_prompt_cols = st.columns(len(EXAMPLE_PROMPTS))
    for index, example_prompt in enumerate(EXAMPLE_PROMPTS):
        with quick_prompt_cols[index]:
            if st.button(example_prompt, key=f"inline_example_prompt_{index}", use_container_width=True):
                st.session_state["queued_prompt"] = example_prompt
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            trace = message.get("trace")
            if trace:
                render_trace(trace)

    prompt = st.chat_input("Ask a crypto market question")
    queued_prompt = st.session_state.pop("queued_prompt", None)
    active_prompt = queued_prompt or prompt

    if active_prompt:
        handle_prompt_submission(active_prompt)
