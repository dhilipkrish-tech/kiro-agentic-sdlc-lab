"""Domain models, enums, and constants for pharmacy claim validation.

This module contains no web/framework logic beyond Pydantic data models, so it is
safe to import from both the pure rules layer and the API layer.
"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# --- Business constants (authoritative) ---------------------------------------

#: Maximum dispensable quantity. A claim with quantity strictly greater than this
#: is rejected with QUANTITY_LIMIT_EXCEEDED.
QUANTITY_LIMIT: int = 60

#: Drug IDs that require prior authorization and are rejected when submitted.
PRIOR_AUTH_DRUG_IDS: frozenset[str] = frozenset({"DRUG-PA-001"})


class ClaimStatus(str, Enum):
    """Deterministic adjudication outcome."""

    PAID = "PAID"
    REJECTED = "REJECTED"


class ReasonCode(str, Enum):
    """Machine-readable reason for a rejection."""

    QUANTITY_LIMIT_EXCEEDED = "QUANTITY_LIMIT_EXCEEDED"
    PRIOR_AUTHORIZATION_REQUIRED = "PRIOR_AUTHORIZATION_REQUIRED"


class ClaimInput(BaseModel):
    """A synthetic pharmacy claim submission.

    Structural validation (Requirements 2-4) is enforced here by Pydantic field
    constraints, so malformed input yields HTTP 422 before any business rule runs.
    """

    model_config = ConfigDict(extra="forbid")

    memberId: str = Field(min_length=1, description="Required, non-empty member id")
    drugId: str = Field(min_length=1, description="Required, non-empty drug id")
    quantity: int = Field(gt=0, description="Must be greater than 0")
    submittedAmount: float = Field(ge=0, description="Must be greater than or equal to 0")


class AdjudicationResult(BaseModel):
    """The deterministic result of adjudicating a claim."""

    status: ClaimStatus
    reasonCode: ReasonCode | None = None
    calculatedAmount: float | None = None
    claim: ClaimInput
