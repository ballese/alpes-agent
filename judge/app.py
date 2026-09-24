"""Judge agent skeleton.

Minimal FastAPI service that will eventually audit the actions of the
primary agent. For now it only echoes the received message so that the
container topology and integration surface can be built out incrementally.
"""

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Judge Agent", version="0.1.0")


class AuditRequest(BaseModel):
    """Payload sent by the primary agent for auditing.

    Kept intentionally small; extend with fields such as ``agent_action``,
    ``trace_id`` or ``tool_calls`` when the real judge logic is added.
    """

    message: str = Field(..., description="Message or action to audit")


class AuditResponse(BaseModel):
    status: str
    received: str


@app.get("/health")
def health() -> dict:
    """Liveness endpoint used by the Docker healthcheck."""
    return {"status": "healthy"}


@app.post("/audit", response_model=AuditResponse)
def audit(req: AuditRequest) -> AuditResponse:
    """Skeleton audit endpoint.

    TODO: replace with real judge logic (LLM-as-judge, rule engine,
    LangSmith trace inspection, etc.).
    """
    return AuditResponse(status="ok", received=req.message)
