"""Pure business rules for pharmacy claim adjudication.

This module intentionally has NO FastAPI / web dependencies. It imports only domain
models, so it can be unit-tested in isolation without starting an HTTP server
(Requirement 8).

Deterministic rule ordering (authoritative, first match wins):
    1. quantity > QUANTITY_LIMIT          -> REJECTED / QUANTITY_LIMIT_EXCEEDED
    2. drugId in PRIOR_AUTH_DRUG_IDS      -> REJECTED / PRIOR_AUTHORIZATION_REQUIRED
    3. otherwise                          -> PAID (calculatedAmount == submittedAmount)
"""

from .models import (
    PRIOR_AUTH_DRUG_IDS,
    QUANTITY_LIMIT,
    AdjudicationResult,
    ClaimInput,
    ClaimStatus,
    ReasonCode,
)


def adjudicate(claim: ClaimInput) -> AdjudicationResult:
    """Adjudicate a structurally valid claim into a deterministic result.

    The input is assumed to already satisfy structural validation (enforced by the
    ``ClaimInput`` model). Rules are evaluated in a fixed order; the first matching
    rejection rule wins, which guarantees quantity limit strictly precedes prior
    authorization.
    """
    # Rule 1: quantity limit (strictly precedes prior authorization).
    if claim.quantity > QUANTITY_LIMIT:
        return AdjudicationResult(
            status=ClaimStatus.REJECTED,
            reasonCode=ReasonCode.QUANTITY_LIMIT_EXCEEDED,
            calculatedAmount=None,
            claim=claim,
        )

    # Rule 2: prior authorization required.
    if claim.drugId in PRIOR_AUTH_DRUG_IDS:
        return AdjudicationResult(
            status=ClaimStatus.REJECTED,
            reasonCode=ReasonCode.PRIOR_AUTHORIZATION_REQUIRED,
            calculatedAmount=None,
            claim=claim,
        )

    # Rule 3: paid. calculatedAmount equals submittedAmount.
    return AdjudicationResult(
        status=ClaimStatus.PAID,
        reasonCode=None,
        calculatedAmount=claim.submittedAmount,
        claim=claim,
    )
