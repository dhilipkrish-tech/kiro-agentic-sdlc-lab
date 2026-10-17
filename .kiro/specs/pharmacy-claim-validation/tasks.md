# Implementation Tasks — Pharmacy Claim Validation

Tasks are ordered for incremental, testable delivery. Each task lists the requirements
it satisfies.

- [x] 1. Scaffold backend project
  - Create `backend/app/` and `backend/tests/` packages, `requirements.txt`, `pytest.ini`.
  - Pin FastAPI, Pydantic v2, Uvicorn, pytest, httpx.
  - _Requirements: R8, R10_

- [x] 2. Implement domain models (`models.py`)
  - `ClaimStatus`, `ReasonCode` enums; `QUANTITY_LIMIT`, `PRIOR_AUTH_DRUG_IDS` constants.
  - `ClaimInput` with Pydantic field constraints (memberId/drugId non-empty, quantity > 0, submittedAmount >= 0, extra="forbid").
  - `AdjudicationResult` model.
  - _Requirements: R2, R3, R4, R7_

- [x] 3. Implement pure business rules (`rules.py`)
  - `adjudicate(claim) -> AdjudicationResult` with deterministic ordering: quantity limit → prior auth → paid.
  - No FastAPI imports (web-free module).
  - _Requirements: R1, R5, R6, R7, R8_

- [x] 4. Write unit tests for rules (`test_rules.py`)
  - Positive (paid + calculatedAmount), negative (quantity 61, DRUG-PA-001), boundary (quantity 60, amount 0).
  - **Precedence: DRUG-PA-001 + quantity 61 → QUANTITY_LIMIT_EXCEEDED, asserting NOT PRIOR_AUTHORIZATION_REQUIRED.**
  - **Precedence boundary: DRUG-PA-001 + quantity 60 → PRIOR_AUTHORIZATION_REQUIRED.**
  - **Determinism: repeated adjudication of identical input → identical result.**
  - _Requirements: R1, R5, R6, R7, R8, R10, R11_

- [x] 5. Implement API layer (`main.py`)
  - FastAPI app, CORS, `GET /api/health`, `POST /api/claims` delegating to `adjudicate`.
  - _Requirements: R1, R8, R9_

- [x] 6. Write API tests (`test_api.py`)
  - Positive PAID, structural 422s (missing memberId, empty drugId, quantity 0, negative amount), business rejections, boundaries, determinism.
  - **Precedence: DRUG-PA-001 + quantity 61 → 200 REJECTED / QUANTITY_LIMIT_EXCEEDED, asserting NOT PRIOR_AUTHORIZATION_REQUIRED.**
  - _Requirements: R1, R2, R3, R4, R5, R6, R10, R11_

- [x] 7. Run and verify backend test suite
  - `pytest` green (20 passed); traceability matrix cases all pass.
  - _Requirements: R10_

- [x] 8. Scaffold React frontend
  - Vite + React project, `package.json`, `vite.config.js`, `index.html`, `src/main.jsx`.
  - _Requirements: R9_

- [x] 9. Implement claim form UI (`App.jsx`, `api.js`)
  - Controlled form, submit → POST, render status/reason/amount, error handling.
  - Stable `data-testid` selectors for Playwright.
  - _Requirements: R9_

- [x] 10. Add Playwright E2E tests (`tests-e2e/`)
  - Config + spec: paid flow, prior-auth rejection, and precedence (DRUG-PA-001 + qty 61). All 3 pass against live servers.
  - _Requirements: R9, R10, R11_

- [x] 11. Write README
  - Setup, run (backend + frontend), test instructions (pytest + Playwright), synthetic-data/no-secrets note, traceability matrix.
  - _Requirements: R10_

- [x] 12. Final verification & commit
  - Run full pytest suite; sanity-check structure; commit to feature branch and open PR.
  - _Requirements: R10_
