# Demo Notes

## Strong Talking Points

- The system separates user experience, orchestration, and external data access into clear services.
- The LLM is grounded with live tool results instead of guessing market data.
- Tool traces make the agent's behavior explainable during the demo.
- The wrapper service creates a stable internal API contract.
- The default stack is fully free: CoinGecko plus a local Ollama model.
- The dashboard is a visualization layer on top of the same normalized tool data, not a separate decision engine.

## Suggested Demo Flow

1. Ask for the current BTC price.
2. Compare BTC and ETH.
3. Ask for trending coins.
4. Ask for a quick market summary.
5. Point to the dashboard tab and show that the same live data powers charts and comparison cards.

## Deployment Story

- Deploy the frontend separately from the backend services.
- Containerize the agent backend and the MCP wrapper independently.
- Inject secrets through environment variables.
- Put a reverse proxy or API gateway in front of backend services.
