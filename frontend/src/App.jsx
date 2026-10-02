import React, { useState } from "react";
import { submitClaim } from "./api.js";

const INITIAL = {
  memberId: "M1001",
  drugId: "DRUG-001",
  quantity: 10,
  submittedAmount: 42.5,
};

export default function App() {
  const [form, setForm] = useState(INITIAL);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  const update = (field) => (e) =>
    setForm({ ...form, [field]: e.target.value });

  const onSubmit = async (e) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    setLoading(true);
    try {
      const payload = {
        memberId: form.memberId,
        drugId: form.drugId,
        quantity: Number(form.quantity),
        submittedAmount: Number(form.submittedAmount),
      };
      const data = await submitClaim(payload);
      setResult(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const statusColor =
    result?.status === "PAID"
      ? "#1a7f37"
      : result?.status === "REJECTED"
      ? "#b42318"
      : "#333";

  return (
    <main style={{ maxWidth: 480, margin: "2rem auto", fontFamily: "system-ui, sans-serif" }}>
      <h1>Pharmacy Claim Validation</h1>
      <p style={{ color: "#666" }}>Submit a synthetic claim to see a deterministic outcome.</p>

      <form onSubmit={onSubmit}>
        <label style={{ display: "block", marginBottom: 12 }}>
          Member ID
          <input
            data-testid="member-id-input"
            value={form.memberId}
            onChange={update("memberId")}
            style={{ width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>

        <label style={{ display: "block", marginBottom: 12 }}>
          Drug ID
          <input
            data-testid="drug-id-input"
            value={form.drugId}
            onChange={update("drugId")}
            style={{ width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>

        <label style={{ display: "block", marginBottom: 12 }}>
          Quantity
          <input
            data-testid="quantity-input"
            type="number"
            value={form.quantity}
            onChange={update("quantity")}
            style={{ width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>

        <label style={{ display: "block", marginBottom: 12 }}>
          Submitted Amount
          <input
            data-testid="amount-input"
            type="number"
            step="0.01"
            value={form.submittedAmount}
            onChange={update("submittedAmount")}
            style={{ width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>

        <button
          data-testid="submit-button"
          type="submit"
          disabled={loading}
          style={{ padding: "10px 20px", cursor: "pointer" }}
        >
          {loading ? "Submitting..." : "Submit Claim"}
        </button>
      </form>

      {error && (
        <div
          data-testid="error-message"
          style={{ marginTop: 20, color: "#b42318" }}
        >
          {error}
        </div>
      )}

      {result && (
        <section style={{ marginTop: 20, padding: 16, border: "1px solid #ddd", borderRadius: 8 }}>
          <h2 style={{ margin: 0 }}>Outcome</h2>
          <p>
            Status:{" "}
            <strong data-testid="result-status" style={{ color: statusColor }}>
              {result.status}
            </strong>
          </p>
          <p>
            Reason:{" "}
            <span data-testid="result-reason">{result.reasonCode ?? "—"}</span>
          </p>
          <p>
            Calculated Amount:{" "}
            <span data-testid="result-amount">
              {result.calculatedAmount ?? "—"}
            </span>
          </p>
        </section>
      )}
    </main>
  );
}
