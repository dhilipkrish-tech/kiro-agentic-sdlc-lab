import { test, expect } from "@playwright/test";

// E2E coverage for the UI flow (Requirement 9). Requires both backend and frontend
// servers running (see README). Uses stable data-testid selectors.

async function fillClaim(page, { memberId, drugId, quantity, amount }) {
  await page.getByTestId("member-id-input").fill(memberId);
  await page.getByTestId("drug-id-input").fill(drugId);
  await page.getByTestId("quantity-input").fill(String(quantity));
  await page.getByTestId("amount-input").fill(String(amount));
  await page.getByTestId("submit-button").click();
}

test("paid claim shows PAID outcome", async ({ page }) => {
  await page.goto("/");
  await fillClaim(page, { memberId: "M1001", drugId: "DRUG-001", quantity: 10, amount: 42.5 });
  await expect(page.getByTestId("result-status")).toHaveText("PAID");
  await expect(page.getByTestId("result-amount")).toHaveText("42.5");
});

test("prior-auth drug shows REJECTED / PRIOR_AUTHORIZATION_REQUIRED", async ({ page }) => {
  await page.goto("/");
  await fillClaim(page, { memberId: "M1001", drugId: "DRUG-PA-001", quantity: 10, amount: 42.5 });
  await expect(page.getByTestId("result-status")).toHaveText("REJECTED");
  await expect(page.getByTestId("result-reason")).toHaveText("PRIOR_AUTHORIZATION_REQUIRED");
});

test("precedence: prior-auth drug over limit shows QUANTITY_LIMIT_EXCEEDED", async ({ page }) => {
  await page.goto("/");
  await fillClaim(page, { memberId: "M1001", drugId: "DRUG-PA-001", quantity: 31, amount: 42.5 });
  await expect(page.getByTestId("result-status")).toHaveText("REJECTED");
  await expect(page.getByTestId("result-reason")).toHaveText("QUANTITY_LIMIT_EXCEEDED");
});
