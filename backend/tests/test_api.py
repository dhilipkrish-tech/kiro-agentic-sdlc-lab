"""API-layer tests using FastAPI's TestClient.

Covers positive adjudication, structural 422 validation, business rejections,
boundaries, precedence (R11), and determinism.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID = {"memberId": "M1001", "drugId": "DRUG-001", "quantity": 10, "submittedAmount": 42.5}


def post(payload):
    return client.post("/api/claims", json=payload)


# --- Health -------------------------------------------------------------------

def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# --- Positive -----------------------------------------------------------------

def test_valid_claim_paid():
    """R1, R7: valid claim -> 200 PAID, calculatedAmount == submittedAmount."""
    resp = post(VALID)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "PAID"
    assert body["reasonCode"] is None
    assert body["calculatedAmount"] == 42.5


# --- Negative structural (R2, R3, R4) -> 422 ----------------------------------

def test_missing_member_id():
    """R2.1: missing memberId -> 422."""
    payload = {k: v for k, v in VALID.items() if k != "memberId"}
    assert post(payload).status_code == 422


def test_empty_drug_id():
    """R2.2: empty drugId -> 422."""
    assert post({**VALID, "drugId": ""}).status_code == 422


def test_quantity_zero_rejected_422():
    """R3.1: quantity 0 -> 422."""
    assert post({**VALID, "quantity": 0}).status_code == 422


def test_negative_amount_422():
    """R4.1: negative submittedAmount -> 422."""
    assert post({**VALID, "submittedAmount": -1}).status_code == 422


# --- Negative business (R5, R6) -> 200 REJECTED -------------------------------

def test_quantity_limit_exceeded():
    """R5.1: quantity 31 -> 200 REJECTED / QUANTITY_LIMIT_EXCEEDED."""
    resp = post({**VALID, "quantity": 31})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "REJECTED"
    assert body["reasonCode"] == "QUANTITY_LIMIT_EXCEEDED"
    assert body["calculatedAmount"] is None


def test_prior_auth():
    """R6.1: DRUG-PA-001 -> 200 REJECTED / PRIOR_AUTHORIZATION_REQUIRED."""
    resp = post({**VALID, "drugId": "DRUG-PA-001"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "REJECTED"
    assert body["reasonCode"] == "PRIOR_AUTHORIZATION_REQUIRED"


# --- Boundary -----------------------------------------------------------------

def test_quantity_boundary_30_paid():
    """R5.2: quantity exactly 30 -> 200 PAID."""
    resp = post({**VALID, "quantity": 30})
    assert resp.status_code == 200
    assert resp.json()["status"] == "PAID"


def test_amount_zero_paid():
    """R4.2: submittedAmount 0 -> 200 PAID."""
    resp = post({**VALID, "submittedAmount": 0})
    assert resp.status_code == 200
    assert resp.json()["status"] == "PAID"


# --- Precedence (R11) ---------------------------------------------------------

def test_precedence_quantity_over_prior_auth():
    """R11.1: DRUG-PA-001 + quantity 31 -> QUANTITY_LIMIT_EXCEEDED, NOT prior auth."""
    resp = post({**VALID, "drugId": "DRUG-PA-001", "quantity": 31})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "REJECTED"
    assert body["reasonCode"] == "QUANTITY_LIMIT_EXCEEDED"
    assert body["reasonCode"] != "PRIOR_AUTHORIZATION_REQUIRED"


# --- Determinism (R11.3) ------------------------------------------------------

def test_determinism():
    """R1, R11.3: identical input submitted repeatedly -> identical responses."""
    payload = {**VALID, "drugId": "DRUG-PA-001", "quantity": 31}
    first = post(payload).json()
    for _ in range(5):
        assert post(payload).json() == first
