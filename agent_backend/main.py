from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent_backend.agent import AgentConfigError, run_crypto_agent

app = FastAPI(title="Crypto Agent Backend", version="1.0.0")


class ChatRequest(BaseModel):
    message: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/chat")
def chat(request: ChatRequest):
    try:
        return run_crypto_agent(request.message)
    except AgentConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Unexpected backend error: {exc}") from exc
