import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { customerMe, memberMe, withSession } from "@/test/session";
import { ProjectPage } from "./ProjectPage";

const PID = "11111111-1111-1111-1111-111111111111";
const base = {
  id: PID,
  slug: "demo",
  name: "Demo",
  client_name: "ACME",
  created_at: "2026-10-01T10:00:00+00:00",
  my_role: "owner",
  settings: { model: "claude-opus-5", check_budget_usd: 1, normalize_budget_usd: 2 },
  storage: { connection_id: "c1", connection_name: "Archive", type: "localfs", root: "demo" },
  llm_consent: null,
};

it("shows storage to internal roles and lets an owner record the consent", async () => {
  const consent = { confirmed_by_name: "Customer Rep", confirmed_at: "2026-10-01T11:00:00+00:00" };
  let recorded = false; // the page reloads the project after recording
  const f = mockFetch([
    {
      path: `/api/v1/projects/${PID}`,
      handler: () => ({ ...base, llm_consent: recorded ? consent : null }),
    },
    {
      method: "POST",
      path: `/api/v1/projects/${PID}/llm-consent`,
      status: 201,
      handler: () => {
        recorded = true;
        return consent;
      },
    },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, memberMe).element);
  expect(await screen.findByRole("heading", { name: "Demo" })).toBeInTheDocument();
  expect(screen.getByText("Archive")).toBeInTheDocument();
  // the storage type is shown with the same label as the create dialog and the admin page
  expect(screen.getByText("Local filesystem")).toBeInTheDocument();
  expect(screen.queryByText("localfs")).toBeNull();
  expect(screen.getByText("demo")).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Members" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Settings" })).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Name of the confirming person"), "Customer Rep");
  await userEvent.click(screen.getByRole("button", { name: "Record customer confirmation" }));
  expect(await screen.findByText(/Confirmed by Customer Rep on/)).toBeInTheDocument();
  expect(await f.body(1)).toEqual({ confirmed_by_name: "Customer Rep" });
});

it("hides storage, members and settings from clients and viewers see no settings tab", async () => {
  mockFetch([
    {
      path: `/api/v1/projects/${PID}`,
      body: { ...base, my_role: "client", settings: null, storage: null },
    },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, customerMe).element);
  expect(await screen.findByRole("heading", { name: "Demo" })).toBeInTheDocument();
  expect(screen.queryByText("Archive")).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Members" })).not.toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Settings" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Name of the confirming person")).not.toBeInTheDocument();
  expect(screen.getByText(/Not confirmed yet/)).toBeInTheDocument();
});

it("reports an unknown project", async () => {
  mockFetch([
    { path: `/api/v1/projects/${PID}`, status: 404, body: { detail: "Project not found." } },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, memberMe).element);
  expect(await screen.findByRole("alert")).toHaveTextContent("Project not found.");
});
