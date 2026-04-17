from __future__ import annotations

import json
import os
import re

from dotenv import load_dotenv
from openai import APIConnectionError, NotFoundError, OpenAI

from agent_backend.prompts import SYSTEM_PROMPT
from agent_backend.tools import SYMBOL_ALIASES, TOOLS, ToolExecutionError, call_tool, normalize_symbol, normalize_tool_arguments, parse_tool_arguments

load_dotenv()
LLM_TIMEOUT_SECONDS = 18


class AgentConfigError(Exception):
    pass


class ToolStep(dict):
    pass


def _build_client() -> OpenAI:
    base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    api_key = os.getenv("LLM_API_KEY", "ollama")
    return OpenAI(base_url=base_url, api_key=api_key)


def _validate_model_config(model: str) -> None:
    if not model:
        raise AgentConfigError("LLM_MODEL is missing. Set it in your .env file.")

    # The default free path is a local Ollama server.
    if os.getenv("LLM_BASE_URL", "http://localhost:11434/v1").startswith("http://localhost:11434"):
        if model == "your_model_here":
            raise AgentConfigError("LLM_MODEL is still a placeholder. Set it to a local Ollama model such as qwen2.5:7b.")


def _extract_assets(text: str) -> list[str]:
    lowered = text.lower()
    assets: list[str] = []
    for alias in sorted(SYMBOL_ALIASES.keys(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            value = normalize_symbol(alias)
            if value not in assets:
                assets.append(value)
    return assets


def _build_planned_steps(user_message: str) -> list[ToolStep]:
    lowered = user_message.lower()
    assets = _extract_assets(user_message)


    # Expanded comparison detection for crypto
    comparison_phrases = [
        "compare", "vs", "versus", "doing better", "performing better", "outperform", "beats", "better than", "which is better", "which coin is better", "who wins", "which is doing better", "which one is doing better"
    ]
    if any(phrase in lowered for phrase in comparison_phrases) and len(assets) >= 2:
        return [
            ToolStep(
                tool="compare_coins",
                arguments={"symbol1": assets[0], "symbol2": assets[1]},
                reason="The user asked for a crypto asset comparison.",
            )
        ]

    if any(phrase in lowered for phrase in ["should i invest", "is it a good time", "which one is better", "better buy", "worth buying"]):
        primary = assets[0] if assets else "btc"
        return [
            ToolStep(
                tool="get_coin_price",
                arguments={"symbol": primary},
                reason="The question asks for current context on a specific asset.",
            ),
            ToolStep(
                tool="get_trending_coins",
                arguments={},
                reason="Trending data helps add current market momentum context.",
            ),
            ToolStep(
                tool="get_market_summary",
                arguments={},
                reason="A market summary helps frame the broader environment before giving a cautious informational answer.",
            ),
        ]

    if any(phrase in lowered for phrase in ["what should i look at", "what is happening in the market", "what should i watch", "market insights right now"]):
        steps = [
            ToolStep(
                tool="get_market_summary",
                arguments={},
                reason="A market snapshot highlights current leaders, laggards, and major assets.",
            )
        ]
        if "trending" in lowered or "watch" in lowered:
            steps.append(
                ToolStep(
                    tool="get_trending_coins",
                    arguments={},
                    reason="Trending assets add lightweight attention context when the prompt asks what to watch.",
                )
            )
        return steps

    if "trending" in lowered or "momentum" in lowered:
        return [
            ToolStep(
                tool="get_trending_coins",
                arguments={},
                reason="The user asked for trending market data.",
            )
        ]

    if "market summary" in lowered or "top coins" in lowered or "market movers" in lowered:
        return [
            ToolStep(
                tool="get_market_summary",
                arguments={},
                reason="The user asked for a broad market snapshot.",
            )
        ]

    if ("trend" in lowered or "last 7 days" in lowered or "chart" in lowered) and assets:
        return [
            ToolStep(
                tool="get_coin_trend",
                arguments={"symbol": assets[0], "days": 7},
                reason="The user asked for a recent movement view suitable for trend analysis.",
            )
        ]

    if any(word in lowered for word in ["price", "trading", "worth", "quote"]) and assets:
        return [
            ToolStep(
                tool="get_coin_price",
                arguments={"symbol": assets[0]},
                reason="The user asked for live asset pricing information.",
            )
        ]

    return []


def _format_currency(value: float | None) -> str:
    if value is None:
        return "data unavailable"
    if value >= 1_000_000_000_000:
        return f"${value / 1_000_000_000_000:.2f}T"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.2f}M"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.6f}"


def _format_change(value: float | None) -> str:
    if value is None:
        return "data unavailable"
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _fallback_response(user_message: str, trace: list[dict]) -> str:
    if not trace:
        return "I could not find grounded market data for that request."

    if any(isinstance(step.get("result"), dict) and "temporarily unavailable" in str(step["result"].get("error", "")).lower() for step in trace):
        return "Live market data is temporarily unavailable because the upstream crypto API is rate-limiting requests, so I’m not going to guess."

    first_tool = trace[0]["tool"]
    first_result = trace[0]["result"]
    if isinstance(first_result, dict) and first_result.get("error"):
        return "Live market data is unavailable right now, so I’m not going to guess."

    if first_tool == "get_coin_price":
        return "\n".join(
            [
                f"{first_result['name']} ({first_result['symbol']})",
                f"Price: {_format_currency(first_result.get('price_usd'))}",
                f"24h Change: {_format_change(first_result.get('change_24h'))}",
                f"Market Cap: {_format_currency(first_result.get('market_cap'))}",
            ]
        )

    if first_tool == "compare_coins":
        coin_1 = first_result["coin_1"]
        coin_2 = first_result["coin_2"]
        return "\n".join(
            [
                f"{coin_1['name']} ({coin_1['symbol']}) vs {coin_2['name']} ({coin_2['symbol']})",
                f"{coin_1['symbol']}: {_format_currency(coin_1.get('price_usd'))}, 24h {_format_change(coin_1.get('change_24h'))}, Market Cap {_format_currency(coin_1.get('market_cap'))}",
                f"{coin_2['symbol']}: {_format_currency(coin_2.get('price_usd'))}, 24h {_format_change(coin_2.get('change_24h'))}, Market Cap {_format_currency(coin_2.get('market_cap'))}",
            ]
        )

    if first_tool == "get_trending_coins":
        coins = first_result.get("coins", [])
        if not coins:
            return "Trending data is unavailable right now, so I’m not going to guess."
        names = ", ".join(f"{coin['name']} ({coin['symbol']})" for coin in coins[:5])
        return f"Currently trending: {names}"

    if first_tool == "get_market_summary":
        leaders = first_result.get("leaders", [])
        laggards = first_result.get("laggards", [])
        top = first_result.get("top_coins", [])
        top_line = ", ".join(f"{coin['name']} ({coin['symbol']})" for coin in top[:5])
        leader_line = ", ".join(f"{coin['name']} {_format_change(coin.get('change_24h'))}" for coin in leaders[:3])
        laggard_line = ", ".join(f"{coin['name']} {_format_change(coin.get('change_24h'))}" for coin in laggards[:3])
        return "\n".join(
            [
                f"Top market names: {top_line}",
                f"Leaders: {leader_line or 'data unavailable'}",
                f"Laggards: {laggard_line or 'data unavailable'}",
            ]
        )

    if first_tool == "get_coin_trend":
        points = first_result.get("points", [])
        if len(points) < 2:
            return "Recent trend data is unavailable right now, so I’m not going to guess."
        start_price = points[0]["price_usd"]
        end_price = points[-1]["price_usd"]
        change_pct = ((end_price - start_price) / start_price * 100) if start_price else 0
        return "\n".join(
            [
                f"{first_result['name']} ({first_result['symbol']})",
                f"7d Start: {_format_currency(start_price)}",
                f"Current: {_format_currency(end_price)}",
                f"7d Change: {_format_change(change_pct)}",
            ]
        )

    if len(trace) > 1 and any(step["tool"] == "get_coin_price" for step in trace):
        price_step = next(step for step in trace if step["tool"] == "get_coin_price")
        asset = price_step["result"]
        return "\n".join(
            [
                f"{asset['name']} ({asset['symbol']})",
                f"Price: {_format_currency(asset.get('price_usd'))}",
                f"24h Change: {_format_change(asset.get('change_24h'))}",
                "Based on current market data, this is an informational view rather than a buy or sell recommendation.",
            ]
        )

    if len(trace) > 1 and any(step["tool"] == "get_market_summary" for step in trace):
        summary = next(step["result"] for step in trace if step["tool"] == "get_market_summary")
        leaders = summary.get("leaders", [])
        top = summary.get("top_coins", [])
        leader_line = ", ".join(f"{coin['name']} {_format_change(coin.get('change_24h'))}" for coin in leaders[:3])
        top_line = ", ".join(f"{coin['name']} ({coin['symbol']})" for coin in top[:5])
        return "\n".join(
            [
                f"Based on current live market data, the market leaders today are: {leader_line or 'data unavailable'}.",
                f"Key names to watch: {top_line or 'data unavailable'}.",
                "This is a decision-support view for exploratory analysis, not a trading recommendation.",
            ]
        )

    return "I found some grounded market data, but I could not turn it into a polished answer."


def _run_planned_tools(planned_steps: list[ToolStep]) -> list[dict]:
    trace: list[dict] = []
    seen_results: dict[tuple[str, str], dict] = {}
    for step in planned_steps:
        normalized_arguments = normalize_tool_arguments(step["tool"], step["arguments"])
        cache_key = (step["tool"], json.dumps(normalized_arguments, sort_keys=True))
        if cache_key in seen_results:
            result = seen_results[cache_key]
        else:
            try:
                result = call_tool(step["tool"], normalized_arguments)
            except ToolExecutionError as exc:
                result = {"error": str(exc)}
            seen_results[cache_key] = result
        trace.append(
            {
                "tool": step["tool"],
                "reason": step["reason"],
                "arguments": normalized_arguments,
                "result": result,
            }
        )
    return trace


def _run_llm_summary(client: OpenAI, model: str, user_message: str, trace: list[dict]) -> str:
    trace_payload = json.dumps(trace, indent=2)
    response = client.chat.completions.create(
        model=model,
        temperature=0.1,
        timeout=LLM_TIMEOUT_SECONDS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"User request: {user_message}\n\n"
                    f"Grounded tool trace:\n{trace_payload}\n\n"
                    "Answer using only this data. If any tool result contains an error, say the data is unavailable and do not guess."
                ),
            },
        ],
    )
    return response.choices[0].message.content or ""


def _should_skip_llm_summary(user_message: str, trace: list[dict]) -> bool:
    lowered = user_message.lower()
    if any(
        phrase in lowered
        for phrase in [
            "what should i look at",
            "what is happening in the market",
            "what should i watch",
            "market insights right now",
            "market summary",
        ]
    ):
        return True
    if len(trace) <= 2 and all(step["tool"] in {"get_market_summary", "get_trending_coins"} for step in trace):
        return True
    return False


def run_crypto_agent(user_message: str) -> dict:
    client = _build_client()
    model = os.getenv("LLM_MODEL", "qwen2.5:7b")
    _validate_model_config(model)

    planned_steps = _build_planned_steps(user_message)
    trace = _run_planned_tools(planned_steps)


    # If no planned steps, force tool usage for crypto queries
    if not trace:
        # Fallback: try to extract assets and force a tool call if crypto terms are present
        assets = _extract_assets(user_message)
        if len(assets) >= 2:
            trace = _run_planned_tools([
                ToolStep(
                    tool="compare_coins",
                    arguments={"symbol1": assets[0], "symbol2": assets[1]},
                    reason="Fallback: forced crypto asset comparison.",
                )
            ])
        elif assets:
            trace = _run_planned_tools([
                ToolStep(
                    tool="get_coin_price",
                    arguments={"symbol": assets[0]},
                    reason="Fallback: forced crypto price lookup.",
                )
            ])
        else:
            # If no crypto assets, fallback to original LLM/tool logic
            trace = []
            seen_results: dict[tuple[str, str], dict] = {}
            messages: list[dict] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]

            for _ in range(5):
                try:
                    response = client.chat.completions.create(
                        model=model,
                        temperature=0.1,
                        messages=messages,
                        tools=TOOLS,
                        tool_choice="auto",
                        timeout=LLM_TIMEOUT_SECONDS,
                    )
                except APIConnectionError as exc:
                    raise AgentConfigError(
                        "Could not reach the local Ollama server at LLM_BASE_URL. Start Ollama and make sure it is listening on http://localhost:11434."
                    ) from exc
                except NotFoundError as exc:
                    raise AgentConfigError(
                        f"The local model '{model}' is not available. Run `ollama pull {model}` and try again."
                    ) from exc
                message = response.choices[0].message

                if message.tool_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": message.content or "",
                            "tool_calls": [
                                {
                                    "id": tool_call.id,
                                    "type": tool_call.type,
                                    "function": {
                                        "name": tool_call.function.name,
                                        "arguments": tool_call.function.arguments,
                                    },
                                }
                                for tool_call in message.tool_calls
                            ],
                        }
                    )

                    for tool_call in message.tool_calls:
                        arguments = parse_tool_arguments(tool_call.function.arguments)
                        normalized_arguments = normalize_tool_arguments(tool_call.function.name, arguments)
                        cache_key = (tool_call.function.name, json.dumps(normalized_arguments, sort_keys=True))
                        if cache_key in seen_results:
                            result = seen_results[cache_key]
                        else:
                            try:
                                result = call_tool(tool_call.function.name, normalized_arguments)
                            except ToolExecutionError as exc:
                                result = {"error": str(exc)}
                            seen_results[cache_key] = result

                        trace.append(
                            {
                                "tool": tool_call.function.name,
                                "reason": "The model selected this tool for the request.",
                                "arguments": normalized_arguments,
                                "result": result,
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": json.dumps(result),
                            }
                        )
                    continue

                return {
                    "response": message.content or _fallback_response(user_message, trace),
                    "trace": trace,
                    "model": model,
                }

            return {"response": _fallback_response(user_message, trace), "trace": trace, "model": model}

    if _should_skip_llm_summary(user_message, trace):
        response_text = _fallback_response(user_message, trace)
    else:
        try:
            response_text = _run_llm_summary(client, model, user_message, trace)
        except (APIConnectionError, NotFoundError):
            response_text = _fallback_response(user_message, trace)

    # Crypto-domain validation guardrail: block unrelated/stock-style answers
    def _is_crypto_response(text: str) -> bool:
        crypto_keywords = [
            "crypto", "coin", "token", "blockchain", "btc", "eth", "sol", "doge", "xrp", "ada", "bnb", "market cap", "price", "trend", "trending", "market summary", "exchange", "satoshi", "ethereum", "bitcoin", "solana", "dogecoin", "ripple", "cardano", "binance"
        ]
        lowered = (text or "").lower()
        return any(word in lowered for word in crypto_keywords)

    response_final = response_text or _fallback_response(user_message, trace)
    if not _is_crypto_response(response_final):
        response_final = "Sorry, I can only answer questions about cryptocurrencies and crypto markets. Please rephrase your question to focus on crypto assets."

    return {
        "response": response_final,
        "trace": trace,
        "model": model,
    }
