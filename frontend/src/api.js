// Thin fetch wrapper around the claim adjudication endpoint.
// The API base defaults to localhost:8000 but can be overridden via VITE_API_BASE.

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export async function submitClaim(claim) {
  const resp = await fetch(`${API_BASE}/api/claims`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(claim),
  });

  const data = await resp.json().catch(() => null);

  if (resp.status === 422) {
    // Structural validation error from FastAPI.
    const detail = data?.detail?.[0]?.msg || "Invalid input";
    throw new Error(`Validation error: ${detail}`);
  }
  if (!resp.ok) {
    throw new Error(`Request failed (${resp.status})`);
  }
  return data;
}
