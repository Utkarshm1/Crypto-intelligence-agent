import unittest
from unittest.mock import Mock, patch

from agent_backend.agent import _build_planned_steps
from agent_backend.tools import normalize_symbol
from mcp_server.services import coingecko_service


class AgentLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        coingecko_service._CACHE.clear()

    def test_normalize_symbol_handles_names_and_typos(self) -> None:
        self.assertEqual(normalize_symbol("bitcoin"), "btc")
        self.assertEqual(normalize_symbol("Etherum"), "eth")
        self.assertEqual(normalize_symbol("solana"), "sol")

    def test_compare_prompt_creates_compare_step(self) -> None:
        steps = _build_planned_steps("Compare bitcoin and ETH today")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["tool"], "compare_coins")
        self.assertEqual(steps[0]["arguments"], {"symbol1": "btc", "symbol2": "eth"})

    def test_market_watch_prompt_uses_multiple_tools(self) -> None:
        steps = _build_planned_steps("What should I look at in the market right now?")
        self.assertEqual([step["tool"] for step in steps], ["get_market_summary"])

    def test_market_watch_prompt_with_watch_keyword_adds_trending(self) -> None:
        steps = _build_planned_steps("What should I watch in the market right now?")
        self.assertEqual([step["tool"] for step in steps], ["get_market_summary", "get_trending_coins"])

    @patch("mcp_server.services.coingecko_service.requests.get")
    def test_wrapper_caches_market_requests_for_ttl_window(self, mock_get: Mock) -> None:
        response = Mock()
        response.json.return_value = [{"symbol": "btc"}]
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        first = coingecko_service._get("/coins/markets", params={"ids": "bitcoin", "vs_currency": "usd"})
        second = coingecko_service._get("/coins/markets", params={"ids": "bitcoin", "vs_currency": "usd"})

        self.assertEqual(first, second)
        self.assertEqual(mock_get.call_count, 1)

    @patch("mcp_server.services.coingecko_service.requests.get")
    def test_wrapper_raises_normalized_rate_limit_error(self, mock_get: Mock) -> None:
        response = Mock()
        response.status_code = 429
        response.raise_for_status.side_effect = coingecko_service.requests.HTTPError("429")
        mock_get.return_value = response

        with self.assertRaises(coingecko_service.CoinGeckoRateLimitError):
            coingecko_service._get("/coins/markets", params={"ids": "bitcoin", "vs_currency": "usd"})


if __name__ == "__main__":
    unittest.main()
