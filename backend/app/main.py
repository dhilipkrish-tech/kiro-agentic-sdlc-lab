"""FastAPI application layer.

This layer is intentionally thin: it handles HTTP concerns (routing, CORS, request
validation via the ``ClaimInput`` model) and delegates all adjudication to the pure
``rules.adjudicate`` function. Business logic does not live here (Requirement 8).

Structural validation failures are returned automatically as HTTP 422 by FastAPI.
Business-rule rejections are returned as HTTP 200 with status=REJECTED and a reasonCode.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .models import AdjudicationResult, ClaimInput
from .rules import adjudicate

app = FastAPI(title="Pharmacy Claim Validation", version="1.0.0")

# Synthetic learning app: no auth, no secrets, no real data, so permissive CORS is fine.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


@app.post("/api/claims", response_model=AdjudicationResult)
def submit_claim(claim: ClaimInput) -> AdjudicationResult:
    """Adjudicate a synthetic pharmacy claim into a deterministic PAID/REJECTED result."""
    return adjudicate(claim)
