# Requirements — Pharmacy Claim Validation

## Introduction

A small synthetic pharmacy claim validation application built for learning agentic
software development. A user submits a synthetic pharmacy claim through a React UI;
the FastAPI backend applies a set of deterministic business rules and returns a
**PAID** or **REJECTED** outcome. All data is synthetic — no real patient data,
credentials, or secrets are used anywhere.

The system is intentionally small and deterministic so that every major requirement
can be traced to an automated test.

## Glossary

- **Claim** — A submitted request containing `memberId`, `drugId`, `quantity`, and `submittedAmount`.
- **Outcome / status** — The deterministic result of validating a claim: `PAID` or `REJECTED`.
- **Reason code** — A machine-readable code explaining a rejection (e.g. `QUANTITY_LIMIT_EXCEEDED`).
- **calculatedAmount** — The amount the plan calculates for a paid claim. For this app, equals `submittedAmount`.

## Claim Input Model

| Field             | Type              | Constraint                        |
| ----------------- | ----------------- | --------------------------------- |
| `memberId`        | string            | required, non-empty               |
| `drugId`          | string            | required, non-empty               |
| `quantity`        | integer / number  | required, must be `> 0`           |
| `submittedAmount` | number            | required, must be `>= 0`          |

## Requirements

### Requirement 1 — Submit a claim and receive a deterministic outcome

**User Story:** As a pharmacy user, I want to submit a claim and receive a clear
PAID or REJECTED result, so that I know whether the claim is adjudicated.

#### Acceptance Criteria

1. WHEN a user submits a valid claim THEN the system SHALL return an outcome of either `PAID` or `REJECTED`.
2. WHEN the same claim input is submitted multiple times THEN the system SHALL return the identical outcome every time (deterministic).
3. WHEN a claim is adjudicated THEN the response SHALL include the `status`, a `reasonCode` (null for paid), and the submitted claim echo.

### Requirement 2 — Required field validation (memberId, drugId)

**User Story:** As a user, I want the system to reject structurally invalid claims,
so that only well-formed claims are adjudicated.

#### Acceptance Criteria

1. WHEN `memberId` is missing or empty THEN the system SHALL return a validation error (HTTP 422) and SHALL NOT adjudicate.
2. WHEN `drugId` is missing or empty THEN the system SHALL return a validation error (HTTP 422) and SHALL NOT adjudicate.

### Requirement 3 — Quantity validation

**User Story:** As a user, I want quantity to be validated, so that nonsensical
quantities are not adjudicated.

#### Acceptance Criteria

1. WHEN `quantity` is less than or equal to 0 THEN the system SHALL return a validation error (HTTP 422).
2. WHEN `quantity` is greater than 0 and less than or equal to 60 THEN the system SHALL treat the quantity as valid for adjudication.

### Requirement 4 — Submitted amount validation

**User Story:** As a user, I want submittedAmount to be validated, so that negative
amounts are rejected before adjudication.

#### Acceptance Criteria

1. WHEN `submittedAmount` is less than 0 THEN the system SHALL return a validation error (HTTP 422).
2. WHEN `submittedAmount` is greater than or equal to 0 THEN the system SHALL treat the amount as valid for adjudication.

### Requirement 5 — Quantity limit business rule

**User Story:** As a plan administrator, I want claims above the quantity limit to be
rejected, so that over-limit dispensing is blocked.

#### Acceptance Criteria

1. WHEN a structurally valid claim has `quantity` greater than 60 THEN the system SHALL return `status = REJECTED` with `reasonCode = QUANTITY_LIMIT_EXCEEDED`.
2. WHEN `quantity` is exactly 60 THEN the system SHALL NOT reject for quantity limit (boundary).

### Requirement 6 — Prior authorization business rule

**User Story:** As a plan administrator, I want drugs requiring prior authorization to
be rejected when submitted without it, so that PA drugs are controlled.

#### Acceptance Criteria

1. WHEN a structurally valid claim has `drugId = "DRUG-PA-001"` THEN the system SHALL return `status = REJECTED` with `reasonCode = PRIOR_AUTHORIZATION_REQUIRED`.
2. WHEN a claim has `drugId = "DRUG-PA-001"` AND also `quantity > 60` THEN the system SHALL reject with `QUANTITY_LIMIT_EXCEEDED` (quantity limit is evaluated first, deterministic rule ordering).

### Requirement 11 — Rule precedence and determinism (explicit coverage)

**User Story:** As a maintainer, I want rule precedence and determinism to be explicitly
and automatically verified, so that the fixed rule ordering can never silently regress.

#### Acceptance Criteria

1. WHEN `drugId = "DRUG-PA-001"` AND `quantity = 61` THEN the system SHALL return `status = REJECTED` with `reasonCode = QUANTITY_LIMIT_EXCEEDED` and SHALL NOT return `PRIOR_AUTHORIZATION_REQUIRED` (quantity limit strictly precedes prior authorization).
2. WHEN `drugId = "DRUG-PA-001"` AND `quantity = 60` (at the quantity boundary) THEN the system SHALL return `status = REJECTED` with `reasonCode = PRIOR_AUTHORIZATION_REQUIRED` (quantity limit does not apply, so prior auth is the governing rule).
3. WHEN any identical claim input is adjudicated repeatedly THEN the system SHALL return byte-for-byte identical results every time (determinism), and this SHALL be asserted by an automated test at both the rules layer and the API layer.
4. The precedence behavior in criterion 1 SHALL be covered by a dedicated automated test at both the rules layer (`test_rules.py`) and the API layer (`test_api.py`).

### Requirement 7 — Paid claim calculation

**User Story:** As a user, I want paid claims to show a calculated amount, so that I can
see the adjudicated payment.

#### Acceptance Criteria

1. WHEN a claim passes all validations and no rejection rule applies THEN the system SHALL return `status = PAID` with `reasonCode = null`.
2. WHEN a claim is PAID THEN `calculatedAmount` SHALL equal `submittedAmount`.
3. WHEN a claim is REJECTED THEN `calculatedAmount` SHALL be `null` (or 0 — see design decision).

### Requirement 8 — Separation of concerns

**User Story:** As a developer, I want business rules isolated from the API layer, so
that rules are independently testable and reusable.

#### Acceptance Criteria

1. The business rules SHALL live in a dedicated module with no FastAPI/web dependencies.
2. The API layer SHALL delegate adjudication to the rules module.
3. The rules module SHALL be unit-testable without starting an HTTP server.

### Requirement 9 — Frontend

**User Story:** As a user, I want a simple web form, so that I can submit a claim and
see the outcome.

#### Acceptance Criteria

1. WHEN a user fills the form and submits THEN the UI SHALL call the backend and display the outcome (`PAID`/`REJECTED`) and any reason code.
2. The UI SHALL expose stable selectors (e.g. `data-testid`) so it is testable with Playwright.
3. The UI SHALL display validation/error feedback returned by the backend.

### Requirement 10 — Quality, data, and documentation

**User Story:** As a maintainer, I want tests, synthetic data, and docs, so the project
is safe and reproducible.

#### Acceptance Criteria

1. The project SHALL include positive, negative, and boundary automated tests (pytest for rules + API).
2. The project SHALL use only synthetic data and SHALL contain no credentials or secrets.
3. The project SHALL include a README with setup, run, and test instructions.
4. Major requirements SHALL be traceable to automated tests (traceability matrix in design/README).

## Deterministic Rule Ordering (authoritative)

Adjudication evaluates in this fixed order (first match wins):

1. Structural validation (memberId, drugId, quantity > 0, submittedAmount >= 0) → HTTP 422 if failing.
2. `quantity > 60` → REJECTED / `QUANTITY_LIMIT_EXCEEDED`.
3. `drugId == "DRUG-PA-001"` → REJECTED / `PRIOR_AUTHORIZATION_REQUIRED`.
4. Otherwise → PAID, `calculatedAmount = submittedAmount`.

## Out of Scope

- Persistence / database.
- Authentication / authorization.
- Real drug pricing, formularies, or external integrations.
- A prior-authorization approval workflow (PA drugs are simply rejected).
