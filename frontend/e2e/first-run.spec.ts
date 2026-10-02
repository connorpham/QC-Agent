import { readFileSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";
import { generate } from "otplib";
import { STATE_FILE } from "./env";

const NEW_PASSWORD = "e2e-very-long-password-2026";

async function signIn(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("E-mail").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
}

test("first run: admin signs in, enrols MFA, changes the password, sets up storage, a project and a member", async ({
  page,
}) => {
  const admin = JSON.parse(readFileSync(STATE_FILE, "utf8")) as { email: string; password: string };

  await test.step("login and MFA enrolment with recovery codes", async () => {
    await signIn(page, admin.email, admin.password);
    await expect(page.getByRole("heading", { name: "Two-factor authentication" })).toBeVisible();
    const secret = await page.getByLabel("Setup key (if you cannot scan)").inputValue();
    await expect(page.getByAltText("QR code for your authenticator app")).toBeVisible();
    await page.getByLabel("Authentication code").fill(await generate({ secret }));
    await page.getByRole("button", { name: "Confirm" }).click();
    await expect(page.getByRole("heading", { name: "Recovery codes" })).toBeVisible();
    await expect(page.getByRole("listitem")).toHaveCount(10);
    const next = page.getByRole("button", { name: "Continue" });
    await expect(next).toBeDisabled();
    await page.getByLabel("I have saved my recovery codes").check();
    await next.click();
  });

  await test.step("forced password change", async () => {
    await expect(page.getByRole("heading", { name: "Change your password" })).toBeVisible();
    await page.getByLabel("Current password").fill(admin.password);
    await page.getByLabel("New password", { exact: true }).fill(NEW_PASSWORD);
    await page.getByLabel("Confirm new password").fill(NEW_PASSWORD);
    await page.getByRole("button", { name: "Change password" }).click();
    await page.waitForURL("**/projects");
    await expect(page.getByText("Administrator")).toBeVisible();
  });

  await test.step("admin creates and tests a storage connection", async () => {
    await page.getByRole("link", { name: "Admin" }).click();
    await page.getByRole("link", { name: "Storage" }).click();
    await expect(page.getByRole("cell", { name: /Local storage/ })).toBeVisible();
    await page.getByRole("button", { name: "New connection" }).click();
    await page.getByLabel("Name", { exact: true }).fill("E2E storage");
    await page.getByLabel("Root path").fill("e2e");
    await page.getByRole("button", { name: "Save" }).click();
    const row = page.getByRole("row", { name: /E2E storage/ });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Test connection" }).click();
    await expect(row.getByRole("status")).toHaveText("Connection OK");
  });

  await test.step("owner creates a project on that connection and records the consent", async () => {
    await page.getByRole("link", { name: "Projects" }).click();
    await page.getByRole("button", { name: "New project" }).click();
    await page.getByLabel("Project name").fill("E2E Project");
    await page.getByLabel("Client name").fill("ACME");
    await page
      .getByLabel("Storage connection")
      .selectOption({ label: "E2E storage (Local filesystem)" });
    await page.getByLabel("Root folder (optional)").fill("e2e-project");
    await page.getByRole("button", { name: "Create project" }).click();
    await page.waitForURL(/\/projects\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { name: "E2E Project" })).toBeVisible();
    await page.getByRole("tab", { name: "Overview" }).click();
    await expect(page.getByText("E2E storage")).toBeVisible();
    await expect(page.getByText("e2e-project")).toBeVisible();
    await page.getByLabel("Name of the confirming person").fill("Customer Rep");
    await page.getByRole("button", { name: "Record customer confirmation" }).click();
    await expect(page.getByText(/Confirmed by Customer Rep on/)).toBeVisible();
  });

  const projectUrl = page.url();

  await test.step("admin creates an editor account and sees the temporary password once", async () => {
    await page.getByRole("link", { name: "Admin" }).click();
    await page.getByRole("button", { name: "Create user" }).click();
    const createDialog = page.getByRole("dialog", { name: "Create user" });
    await createDialog.getByLabel("E-mail").fill("editor@example.com");
    await createDialog.getByLabel("Display name").fill("Editor");
    // Scoped to the dialog: the page also has a "Create user" button whose accessible name
    // contains "Create", which would otherwise make this locator ambiguous.
    await createDialog.getByRole("button", { name: "Create", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Temporary password" });
    await expect(dialog).toBeVisible();
    await expect(dialog.locator("code")).toHaveText(/\S{12,}/);
    await dialog.getByRole("button", { name: "Close" }).click();
    await expect(dialog).toBeHidden();
    await expect(page.getByRole("cell", { name: "editor@example.com" })).toBeVisible();
  });

  await test.step("owner adds the editor as a project member", async () => {
    await page.goto(projectUrl);
    await page.getByRole("tab", { name: "Members" }).click();
    await page
      .getByLabel("User", { exact: true })
      .selectOption({ label: "Editor (editor@example.com)" });
    await page.getByLabel("Role", { exact: true }).selectOption("editor");
    await page.getByRole("button", { name: "Add member" }).click();
    await page.getByRole("button", { name: "Save members" }).click();
    await expect(page.getByRole("status")).toHaveText("Members saved.");
    // exact: true — "Editor" would otherwise also match the "editor@example.com" and
    // "Role: Editor" cells in the same row (substring name matching).
    await expect(page.getByRole("cell", { name: "Editor", exact: true })).toBeVisible();
  });

  await test.step("logout", async () => {
    await page.getByRole("button", { name: "Log out" }).click();
    await page.waitForURL("**/login");
  });
});
