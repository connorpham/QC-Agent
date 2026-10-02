import { expect, test } from "@playwright/test";
import { SAMPLE_DOCX } from "./env";
import { signIn } from "./helpers";

test.describe.configure({ mode: "serial" });

let documentUrl = "";

test("upload with a chosen type, live progress over SSE, read, download, gap report", async ({
  page,
}) => {
  await signIn(page);

  await test.step("open the project created by first-run on its Documents tab", async () => {
    await page.getByRole("link", { name: "E2E Project" }).click();
    await expect(page.getByRole("tab", { name: "Documents", selected: true })).toBeVisible();
    await expect(page.getByText("Placeholder").first()).toBeVisible(); // stubs for required types
  });

  await test.step("upload a .docx as an SRS", async () => {
    await page.getByRole("link", { name: "Upload documents" }).click();
    await page.getByLabel("Choose files").setInputFiles(SAMPLE_DOCX);
    const row = page.getByRole("listitem").first();
    await expect(row.getByLabel("Title")).toHaveValue("sample");
    await row.getByLabel("Title").fill("E2E SRS");
    await row
      .getByLabel("Document type")
      .selectOption({ label: "Software Requirements Specification" });
    const sse = page.waitForRequest((request) => request.url().includes("/events"));
    await page.getByRole("button", { name: "Upload" }).click();
    await page.waitForURL(/\/uploads\/[0-9a-f-]{36}$/);
    await sse; // the progress page subscribed to the event stream
  });

  await test.step("watch it publish live", async () => {
    await expect(page.getByRole("heading", { name: "Upload progress" })).toBeVisible();
    await expect(page.getByText("Published")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("status", { name: "Connection" })).toHaveText(
      "All files have been processed.",
    );
    await page.getByRole("link", { name: "Open document" }).click();
    await page.waitForURL(/\/documents\/[0-9a-f-]{36}$/);
    documentUrl = page.url();
  });

  await test.step("read the rendered Markdown and the details", async () => {
    await expect(page.getByRole("heading", { name: "E2E SRS" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Scope" })).toBeVisible();
    await expect(
      page.getByText("The system shall allow users to log in with a password and a one-time code."),
    ).toBeVisible();
    await page.getByText("Details").click();
    // The <details> disclosure (FrontmatterPanel) gets no accessible name from its <summary>
    // text (role=group, unnamed in the a11y tree), so it is scoped by the native tag instead.
    const details = page.locator("details", { hasText: "Details" });
    await expect(details.getByText("Software Requirements Specification")).toBeVisible();
    await expect(details.getByText("Type check skipped")).toBeVisible();
  });

  await test.step("download the original and the Markdown", async () => {
    const [original] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Download original" }).first().click(),
    ]);
    expect(original.suggestedFilename()).toBe("srs--e2e-srs.docx");
    const [markdown] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Download Markdown" }).first().click(),
    ]);
    expect(markdown.suggestedFilename()).toBe("srs--e2e-srs.md");
  });

  await test.step("the gap report shows the SRS present", async () => {
    await page.getByRole("link", { name: "Back to project" }).click();
    await page.getByRole("tab", { name: "Gap report" }).click();
    const table = page.getByRole("table", { name: "02-requirements (What)" });
    const srsRow = table.getByRole("row", { name: /Software Requirements Specification/ });
    await expect(srsRow.getByText("Present")).toBeVisible();
    await expect(
      table.getByRole("row", { name: /Business Requirements Document/ }).getByText("Placeholder"),
    ).toBeVisible();
  });

  await test.step("My tasks is empty (no mismatch with the production analyzer)", async () => {
    await page.getByRole("link", { name: "My tasks" }).click();
    await expect(page.getByText("Nothing is waiting for you.")).toBeVisible();
  });
});

test.describe("on a phone", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("navigation collapses, the document page reads without horizontal scroll", async ({
    page,
  }) => {
    await signIn(page);
    const menu = page.getByRole("button", { name: "Open menu" });
    await expect(menu).toBeVisible();
    await expect(page.getByRole("link", { name: "My tasks" })).toBeHidden();
    await menu.click();
    await expect(page.getByRole("link", { name: "My tasks" })).toBeVisible();
    await page.getByRole("link", { name: "Projects" }).click();
    await expect(page.getByRole("button", { name: "Open menu" })).toBeVisible(); // closed after navigating
    await page.goto(documentUrl);
    await expect(page.getByRole("heading", { name: "E2E SRS" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Markdown" })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await page.getByRole("tab", { name: "Versions" }).click();
    await expect(page.getByText("Version 1")).toBeVisible();
  });
});
