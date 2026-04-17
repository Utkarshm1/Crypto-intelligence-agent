# Demo Script

## Suggested Demo Flow

1. Open the dashboard tab and show the live market metrics, top-performing assets, and comparison section.
2. Ask a direct price question:
   `What is the current price of Bitcoin?`
3. Ask a comparison question:
   `Compare BTC and ETH today`
4. Ask a broader exploratory prompt:
   `What should I look at in the market right now?`

## Sample Talk Track

### Product

This is a local agentic crypto intelligence app for decision-support and exploratory market analysis. It combines a local LLM with tool-calling and a lightweight dashboard, while grounding live market answers in wrapper-normalized data.

### Architecture

The frontend sends chat requests to a FastAPI agent backend. The backend chooses tools and routes all market data access through a separate MCP-style wrapper service. That wrapper talks to CoinGecko, normalizes the data, and adds lightweight resilience with caching and timeout handling.

### Transparency

The UI includes an execution trace that shows which tools ran, what input they received, and what data came back. That makes the app easier to explain without exposing hidden reasoning.

### Reliability

The free upstream API can be slow or rate-limited, so the current implementation includes short-lived caching and constrained fast paths for broad prompts to keep the demo responsive.
