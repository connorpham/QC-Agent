import { readFileSync } from "node:fs";
import { expect, type Page } from "@playwright/test";
import { generate } from "otplib";
import { STATE_FILE } from "./env";

export type AdminState = { email: string; password: string; totpSecret: string };

export function adminState(): AdminState {
  const state = JSON.parse(readFileSync(STATE_FILE, "utf8")) as Partial<AdminState>;
  if (!state.totpSecret) throw new Error("first-run.spec.ts must run first: no TOTP secret saved");
  return state as AdminState;
}

const TOTP_STEP_MS = 30_000;

/** Milliseconds until the TOTP period rolls over to a step that has not been used yet (plus a
 * small buffer for clock skew between this process and the backend). */
function msUntilNextTotpStep(): number {
  return TOTP_STEP_MS - (Date.now() % TOTP_STEP_MS) + 1_000;
}

/** Sign in as the administrator created by first-run.spec.ts: password, then a TOTP code. */
export async function signIn(page: Page): Promise<void> {
  const admin = adminState();
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(admin.email);
  await page.getByLabel("Password").fill(admin.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Two-factor authentication" })).toBeVisible();
  const codeField = page.getByLabel("Authentication or recovery code");
  const verify = page.getByRole("button", { name: "Verify" });
  // A code generated moments after MFA enrolment (first-run.spec.ts) or another recent sign-in
  // can land in the same 30s TOTP step as a code already consumed; the backend's anti-replay
  // check rejects a repeated step (app/services/mfa.py: _advance_totp_counter). Five wrong codes
  // lock the account for 15 minutes (app/services/auth.py: login_max_failures), so this waits
  // for an unused step before each retry rather than hammering the same one.
  // This loop's own cap of 3 attempts is safe only because a successful second factor resets
  // the backend's failure counter (app/services/mfa.py) before it reaches the five-attempt
  // lockout threshold enforced in backend/app/services/auth.py (login_max_failures).
  let attempts = 0;
  for (;;) {
    attempts += 1;
    await codeField.fill(await generate({ secret: admin.totpSecret }));
    await verify.click();
    const navigated = await page
      .waitForURL("**/projects", { timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    if (navigated) return;
    // getByText, not getByRole("alert"): Next.js's route announcer also carries role="alert"
    // (normally empty), which would otherwise make a role-based locator ambiguous.
    await expect(page.getByText("Invalid code.", { exact: true })).toBeVisible();
    if (attempts >= 3) throw new Error("MFA verification kept failing with a fresh code each time");
    await page.waitForTimeout(msUntilNextTotpStep());
  }
}
