"""Unit tests for the pure business rules (no HTTP server involved).

Covers positive, negative, boundary, precedence, and determinism cases.
These tests import only the rules/models layer, demonstrating Requirement 8
(business rules are unit-testable in isolation).
"""

from app.models import ClaimInput, ClaimStatus, ReasonCode
from app.rules import adjudicate


def make_claim(**overrides):
    base = dict(memberId="M1001", drugId="DRUG-001", quantity=10, submittedAmount=42.5)
    base.update(overrides)
    return ClaimInput(**base)


# --- Positive -----------------------------------------------------------------

def test_paid_calculated_amount():
    """R1, R7: a valid claim is PAID and calculatedAmount == submittedAmount."""
    result = adjudicate(make_claim(submittedAmount=42.5))
    assert result.status is ClaimStatus.PAID
    assert result.reasonCode is None
    assert result.calculatedAmount == 42.5


# --- Negative (business rejections) -------------------------------------------

def test_quantity_over_limit():
    """R5: quantity 31 -> REJECTED / QUANTITY_LIMIT_EXCEEDED."""
    result = adjudicate(make_claim(quantity=31))
    assert result.status is ClaimStatus.REJECTED
    assert result.reasonCode is ReasonCode.QUANTITY_LIMIT_EXCEEDED
    assert result.calculatedAmount is None


def test_prior_auth():
    """R6: DRUG-PA-001 -> REJECTED / PRIOR_AUTHORIZATION_REQUIRED."""
    result = adjudicate(make_claim(drugId="DRUG-PA-001"))
    assert result.status is ClaimStatus.REJECTED
    assert result.reasonCode is ReasonCode.PRIOR_AUTHORIZATION_REQUIRED
    assert result.calculatedAmount is None


# --- Boundary -----------------------------------------------------------------

def test_quantity_boundary_30():
    """R3, R5: quantity exactly 30 is within limit -> PAID."""
    result = adjudicate(make_claim(quantity=30))
    assert result.status is ClaimStatus.PAID
    assert result.reasonCode is None


def test_amount_zero_paid():
    """R4: submittedAmount 0 is valid -> PAID with calculatedAmount 0."""
    result = adjudicate(make_claim(submittedAmount=0))
    assert result.status is ClaimStatus.PAID
    assert result.calculatedAmount == 0


# --- Precedence (R11) ---------------------------------------------------------

def test_precedence_quantity_over_prior_auth():
    """R11.1: DRUG-PA-001 + quantity 31 -> QUANTITY_LIMIT_EXCEEDED, NOT prior auth."""
    result = adjudicate(make_claim(drugId="DRUG-PA-001", quantity=31))
    assert result.status is ClaimStatus.REJECTED
    assert result.reasonCode is ReasonCode.QUANTITY_LIMIT_EXCEEDED
    assert result.reasonCode is not ReasonCode.PRIOR_AUTHORIZATION_REQUIRED


def test_precedence_boundary_prior_auth():
    """R11.2: DRUG-PA-001 + quantity 30 -> PRIOR_AUTHORIZATION_REQUIRED (qty within limit)."""
    result = adjudicate(make_claim(drugId="DRUG-PA-001", quantity=30))
    assert result.status is ClaimStatus.REJECTED
    assert result.reasonCode is ReasonCode.PRIOR_AUTHORIZATION_REQUIRED


# --- Determinism (R11.3) ------------------------------------------------------

def test_determinism():
    """R1, R11.3: repeated adjudication of identical input -> identical result."""
    claim = make_claim(drugId="DRUG-PA-001", quantity=31)
    first = adjudicate(claim)
    for _ in range(5):
        assert adjudicate(claim).model_dump() == first.model_dump()
