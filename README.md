# Pharmacy Claim Validation

A small **synthetic** pharmacy claim validation application built for learning agentic
software development. Submit a synthetic claim and receive a deterministic **PAID** or
**REJECTED** outcome.

> ⚠️ All data is synthetic. There is no real patient data, no credentials, and no secrets
> anywhere in this project.

## What it does

A user submits a claim with four fields:

| Field             | Type   | Constraint                       |
| ----------------- | ------ | -------------------------------- |
| `memberId`        | string | required, non-empty              |
| `drugId`          | string | required, non-empty              |
| `quantity`        | int    | must be `> 0`                    |
| `submittedAmount` | number | must be `>= 0`                   |

The backend applies deterministic business rules in a **fixed order (first match wins):**

1. `quantity > 30` → **REJECTED** / `QUANTITY_LIMIT_EXCEEDED`
2. `drugId == "DRUG-PA-001"` → **REJECTED** / `PRIOR_AUTHORIZATION_REQUIRED`
3. otherwise → **PAID**, with `calculatedAmount == submittedAmount`

Because quantity limit is evaluated **before** prior authorization, a prior-auth drug
submitted over the limit (e.g. `DRUG-PA-001` with `quantity = 31`) is rejected with
`QUANTITY_LIMIT_EXCEEDED`, **not** `PRIOR_AUTHORIZATION_REQUIRED`.

Structural/input validation failures (missing fields, `quantity <= 0`, negative amount)
return **HTTP 422**. Business-rule rejections return **HTTP 200** with
`status = REJECTED` and a `reasonCode`.

## Architecture

Business rules are strictly separated from the API layer:

- `backend/app/rules.py` — **pure** adjudication logic, no web dependencies, unit-testable in isolation.
- `backend/app/models.py` — Pydantic models, enums, and constants (input validation).
- `backend/app/main.py` — thin FastAPI layer that delegates to `rules.adjudicate`.
- `frontend/` — Vite + React single-page form with stable `data-testid` selectors.
- `tests-e2e/` — Playwright UI tests.

See [`.kiro/specs/pharmacy-claim-validation/`](.kiro/specs/pharmacy-claim-validation/)
for the requirements, design, and task artifacts.

## Prerequisites

- Python 3.11+
- Node.js 20+

## Backend — setup, run, test

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run the API (http://localhost:8000, docs at /docs)
python -m uvicorn app.main:app --reload --port 8000

# Run tests (unit + API: positive, negative, boundary, precedence, determinism)
python -m pytest
```

### API

`POST /api/claims`

Request:
```json
{ "memberId": "M1001", "drugId": "DRUG-001", "quantity": 10, "submittedAmount": 42.5 }
```

Paid response (200):
```json
{ "status": "PAID", "reasonCode": null, "calculatedAmount": 42.5, "claim": { ... } }
```

Rejected response (200):
```json
{ "status": "REJECTED", "reasonCode": "QUANTITY_LIMIT_EXCEEDED", "calculatedAmount": null, "claim": { ... } }
```

`GET /api/health` → `{ "status": "ok" }`

## Frontend — setup, run

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 (dev server)
# or build + preview:
npm run build && npm run preview
```

The frontend calls the backend at `http://localhost:8000` by default. Override with the
`VITE_API_BASE` environment variable if needed.

## End-to-end tests (Playwright)

The E2E tests require **both** servers running. In two terminals start the backend
(`port 8000`) and the frontend (`port 5173`), then:

```bash
cd tests-e2e
npm install
npx playwright install chromium   # downloads the browser (needs network access)
npx playwright test
```

If `playwright install` cannot reach the download CDN but a compatible Chromium is
already present on the machine, point Playwright at it:

```bash
PW_CHROME_PATH=/path/to/chrome npx playwright test
```

## Testing philosophy & coverage

The suite includes **positive**, **negative**, and **boundary** cases, plus explicit
**precedence** and **determinism** coverage. Major requirements are traceable to tests:

| Requirement | Covered by |
| ----------- | ---------- |
| R1 deterministic outcome | `test_api.py::test_determinism`, rules paid/reject cases |
| R2 required fields | `test_api.py::test_missing_member_id`, `test_empty_drug_id` |
| R3 quantity > 0 | `test_api.py::test_quantity_zero_rejected_422`; boundary `test_rules.py::test_quantity_boundary_30` |
| R4 submittedAmount >= 0 | `test_api.py::test_negative_amount_422`; boundary `test_rules.py::test_amount_zero_paid` |
| R5 quantity limit | `test_rules.py::test_quantity_over_limit`, `test_api.py::test_quantity_limit_exceeded` |
| R6 prior auth | `test_rules.py::test_prior_auth`, `test_api.py::test_prior_auth` |
| R7 paid calculation | `test_rules.py::test_paid_calculated_amount` |
| R8 separation of concerns | `test_rules.py` imports only rules/models (no HTTP server) |
| R9 frontend | `tests-e2e/claim.spec.js` |
| R10 quality/docs | full pytest suite + this README |
| **R11 precedence** (DRUG-PA-001 + qty 31 → QUANTITY_LIMIT_EXCEEDED) | `test_rules.py::test_precedence_quantity_over_prior_auth`, `test_api.py::test_precedence_quantity_over_prior_auth`, `tests-e2e/claim.spec.js` |
| **R11 precedence boundary** (DRUG-PA-001 + qty 30 → PRIOR_AUTHORIZATION_REQUIRED) | `test_rules.py::test_precedence_boundary_prior_auth` |
| **R11 determinism** | `test_rules.py::test_determinism`, `test_api.py::test_determinism` |

## Project structure

```
backend/
  app/        models.py · rules.py · main.py
  tests/      test_rules.py · test_api.py
  requirements.txt · pytest.ini
frontend/
  src/        App.jsx · api.js · main.jsx
  index.html · package.json · vite.config.js
tests-e2e/
  claim.spec.js · playwright.config.js · package.json
.kiro/specs/pharmacy-claim-validation/
  requirements.md · design.md · tasks.md
```
