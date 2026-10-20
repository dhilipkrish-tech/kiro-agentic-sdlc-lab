# Technical Design — Pharmacy Claim Validation

## Overview

A two-tier application:

- **Backend** — Python + FastAPI. A pure business-rules module (`rules.py`) does
  adjudication; a thin API layer (`main.py`) handles HTTP, request validation
  (Pydantic), and delegates to the rules module.
- **Frontend** — A simple React (Vite) single-page form that posts a claim to the
  backend and renders the outcome. Stable `data-testid` selectors make it
  Playwright-testable.

The core design principle (Requirement 8) is strict separation: **business rules have
zero web dependencies** and are unit-testable in isolation.

## Architecture

```
┌─────────────────────┐        HTTP POST /api/claims        ┌──────────────────────────┐
│   React Frontend     │ ──────────────────────────────────▶ │   FastAPI API layer       │
│   (Vite dev server)  │ ◀────────────────────────────────── │   main.py                 │
│   ClaimForm + result │        JSON: AdjudicationResult      │   - Pydantic validation   │
└─────────────────────┘                                       │   - delegates to rules    │
                                                               └────────────┬──────────────┘
                                                                            │ pure function call
                                                                            ▼
                                                               ┌──────────────────────────┐
                                                               │   rules.py (no web deps)  │
                                                               │   adjudicate(claim)        │
                                                               └──────────────────────────┘
```

## Project Structure

```
kiro-agentic-sdlc-lab/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── models.py        # Pydantic + domain dataclasses, enums, constants
│   │   ├── rules.py         # Pure business logic: adjudicate() — NO FastAPI imports
│   │   └── main.py          # FastAPI app, endpoint, CORS, delegates to rules
│   ├── tests/
│   │   ├── __init__.py
│   │   ├── test_rules.py    # Unit tests for pure rules (positive/negative/boundary)
│   │   └── test_api.py      # API tests via FastAPI TestClient
│   ├── requirements.txt
│   └── pytest.ini
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx          # ClaimForm + outcome display, data-testid selectors
│       └── api.js           # fetch wrapper to backend
├── tests-e2e/               # Playwright UI tests
│   ├── package.json
│   ├── playwright.config.js
│   └── claim.spec.js
└── README.md
```

## Backend Design

### Data models (`models.py`)

```python
from enum import Enum
from pydantic import BaseModel, Field, ConfigDict

QUANTITY_LIMIT = 60
PRIOR_AUTH_DRUG_IDS = {"DRUG-PA-001"}

class ClaimStatus(str, Enum):
    PAID = "PAID"
    REJECTED = "REJECTED"

class ReasonCode(str, Enum):
    QUANTITY_LIMIT_EXCEEDED = "QUANTITY_LIMIT_EXCEEDED"
    PRIOR_AUTHORIZATION_REQUIRED = "PRIOR_AUTHORIZATION_REQUIRED"

class ClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    memberId: str = Field(min_length=1)
    drugId: str = Field(min_length=1)
    quantity: int = Field(gt=0)          # Requirement 3: > 0 → 422 if violated
    submittedAmount: float = Field(ge=0) # Requirement 4: >= 0 → 422 if violated

class AdjudicationResult(BaseModel):
    status: ClaimStatus
    reasonCode: ReasonCode | None = None
    calculatedAmount: float | None = None
    claim: ClaimInput
```

**Validation strategy.** Structural rules (Requirements 2–4) are enforced by Pydantic
`Field` constraints, so malformed input yields HTTP 422 automatically *before* business
logic runs. This cleanly separates input validation from business adjudication.

**Design decision (Req 7.3):** `calculatedAmount` is `null` for rejected claims. This is
unambiguous and easy to assert in tests.

### Business rules (`rules.py`) — pure, no web deps

```python
from .models import (ClaimInput, AdjudicationResult, ClaimStatus,
                     ReasonCode, QUANTITY_LIMIT, PRIOR_AUTH_DRUG_IDS)

def adjudicate(claim: ClaimInput) -> AdjudicationResult:
    # Deterministic rule ordering (authoritative). First match wins.
    # 1. quantity limit
    if claim.quantity > QUANTITY_LIMIT:
        return AdjudicationResult(status=ClaimStatus.REJECTED,
                                  reasonCode=ReasonCode.QUANTITY_LIMIT_EXCEEDED,
                                  calculatedAmount=None, claim=claim)
    # 2. prior authorization
    if claim.drugId in PRIOR_AUTH_DRUG_IDS:
        return AdjudicationResult(status=ClaimStatus.REJECTED,
                                  reasonCode=ReasonCode.PRIOR_AUTHORIZATION_REQUIRED,
                                  calculatedAmount=None, claim=claim)
    # 3. paid
    return AdjudicationResult(status=ClaimStatus.PAID, reasonCode=None,
                              calculatedAmount=claim.submittedAmount, claim=claim)
```

> `adjudicate` imports only models — no FastAPI. It can be unit-tested directly
> (Requirement 8.3).

### API layer (`main.py`)

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .models import ClaimInput, AdjudicationResult
from .rules import adjudicate

app = FastAPI(title="Pharmacy Claim Validation")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.post("/api/claims", response_model=AdjudicationResult)
def submit_claim(claim: ClaimInput) -> AdjudicationResult:
    return adjudicate(claim)
```

`allow_origins=["*"]` is acceptable here because this is a synthetic learning app with
no secrets, no auth, and no real data.

### API contract

`POST /api/claims`

Request body:
```json
{ "memberId": "M1001", "drugId": "DRUG-001", "quantity": 10, "submittedAmount": 42.5 }
```

Success (200) — paid:
```json
{ "status": "PAID", "reasonCode": null, "calculatedAmount": 42.5,
  "claim": { "memberId": "M1001", "drugId": "DRUG-001", "quantity": 10, "submittedAmount": 42.5 } }
```

Rejected (200):
```json
{ "status": "REJECTED", "reasonCode": "QUANTITY_LIMIT_EXCEEDED",
  "calculatedAmount": null, "claim": { ... } }
```

Validation error (422): standard FastAPI validation error payload.

## Frontend Design

- **Vite + React**, single `App.jsx` with a controlled form.
- Fields: `memberId`, `drugId`, `quantity`, `submittedAmount`.
- On submit, `api.js` POSTs to `${VITE_API_BASE}/api/claims` (default `http://localhost:8000`).
- Result area shows status (color-coded), reason code, and calculated amount.
- `data-testid` selectors: `member-id-input`, `drug-id-input`, `quantity-input`,
  `amount-input`, `submit-button`, `result-status`, `result-reason`,
  `result-amount`, `error-message`.

## Testing Strategy

### Unit tests — `test_rules.py` (pure rules)
- Positive: valid claim → PAID, calculatedAmount == submittedAmount.
- Negative: quantity 61 → QUANTITY_LIMIT_EXCEEDED; DRUG-PA-001 → PRIOR_AUTHORIZATION_REQUIRED.
- Boundary: quantity 60 → PAID; submittedAmount 0 → PAID.
- **Precedence: DRUG-PA-001 with quantity 61 → QUANTITY_LIMIT_EXCEEDED, explicitly asserting it is NOT PRIOR_AUTHORIZATION_REQUIRED (quantity first).**
- **Precedence boundary: DRUG-PA-001 with quantity 60 → PRIOR_AUTHORIZATION_REQUIRED (quantity limit does not apply).**
- **Determinism: adjudicating the same input repeatedly returns identical results.**

### API tests — `test_api.py` (FastAPI TestClient)
- Positive: valid claim → 200 PAID.
- Negative structural: missing memberId / empty drugId / quantity 0 / negative amount → 422.
- Negative business: quantity 61 → 200 REJECTED; DRUG-PA-001 → 200 REJECTED.
- Boundary: quantity 60 → PAID; amount 0 → PAID.
- **Precedence: DRUG-PA-001 with quantity 61 → 200 REJECTED with QUANTITY_LIMIT_EXCEEDED, explicitly asserting it is NOT PRIOR_AUTHORIZATION_REQUIRED.**
- Determinism: same input twice → identical response.

### E2E — Playwright (`tests-e2e/claim.spec.js`)
- Submit a paid claim → UI shows PAID.
- Submit DRUG-PA-001 → UI shows REJECTED + PRIOR_AUTHORIZATION_REQUIRED.
- (Playwright config documented; run requires both servers up.)

## Requirement → Test Traceability Matrix

| Requirement | Covered by |
| ----------- | ---------- |
| R1 deterministic outcome | `test_api.py::test_determinism`, `test_rules.py` paid/reject cases |
| R2 required fields | `test_api.py::test_missing_member_id`, `test_empty_drug_id` |
| R3 quantity > 0 | `test_api.py::test_quantity_zero_rejected_422`; boundary `test_rules.py::test_quantity_boundary_30` |
| R4 submittedAmount >= 0 | `test_api.py::test_negative_amount_422`; boundary `test_rules.py::test_amount_zero_paid` |
| R5 quantity limit | `test_rules.py::test_quantity_over_limit`, `test_api.py::test_quantity_limit_exceeded` |
| R6 prior auth | `test_rules.py::test_prior_auth`, `test_api.py::test_prior_auth` |
| R7 paid calculation | `test_rules.py::test_paid_calculated_amount` |
| R11 precedence (DRUG-PA-001 + qty 61 → QUANTITY_LIMIT_EXCEEDED) | `test_rules.py::test_precedence_quantity_over_prior_auth`, `test_api.py::test_precedence_quantity_over_prior_auth` |
| R11 precedence boundary (DRUG-PA-001 + qty 60 → PRIOR_AUTHORIZATION_REQUIRED) | `test_rules.py::test_precedence_boundary_prior_auth` |
| R11 determinism | `test_rules.py::test_determinism`, `test_api.py::test_determinism` |
| R8 separation | `test_rules.py` imports only rules/models (no HTTP) |
| R9 frontend | `tests-e2e/claim.spec.js` |
| R10 quality/docs | full pytest suite + README |

## Technology & Versions

- Python 3.11, FastAPI, Pydantic v2, Uvicorn, pytest, httpx (TestClient).
- Node 22, React 18, Vite 5.
- Playwright (`@playwright/test`).

## Risks / Notes

- Pydantic v2 required for `model_config`/`ConfigDict` syntax; pinned in requirements.txt.
- E2E tests need both servers running; README documents the manual steps. Unit + API
  tests are fully self-contained and are the primary traceability vehicle.
