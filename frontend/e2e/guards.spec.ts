import { expect, test } from "@playwright/test";

test("anonymous visitors are sent to the login page", async ({ page }) => {
  await page.goto("/projects");
  await page.waitForURL("**/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.goto("/admin/storage");
  await page.waitForURL("**/login");
});

test("the API proxy keeps the CSRF guard", async ({ request }) => {
  const health = await request.get("/api/v1/health");
  expect(health.status()).toBe(200);
  const noHeader = await request.post("/api/v1/auth/login", {
    data: { email: "nobody@example.com", password: "x" },
  });
  expect(noHeader.status()).toBe(403);
});
