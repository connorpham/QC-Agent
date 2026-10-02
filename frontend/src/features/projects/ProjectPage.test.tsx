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
const taxonomy = { version: 1, folders: [] };

it("lands on Documents, shows storage on Overview to internal roles and lets an owner record the consent", async () => {
  const consent = { confirmed_by_name: "Customer Rep", confirmed_at: "2026-10-01T11:00:00+00:00" };
  let recorded = false; // the page reloads the project after recording
  const f = mockFetch([
    {
      path: `/api/v1/projects/${PID}`,
      handler: () => ({ ...base, llm_consent: recorded ? consent : null }),
    },
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: [] },
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
  expect(screen.getByRole("tab", { name: "Documents" })).toHaveAttribute("aria-selected", "true");
  expect(await screen.findByText("No documents match these filters.")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Upload documents" })).toHaveAttribute(
    "href",
    `/projects/${PID}/upload`,
  );
  for (const name of ["Overview", "Gap report", "Members", "Settings"]) {
    expect(screen.getByRole("tab", { name })).toBeInTheDocument();
  }
  await userEvent.click(screen.getByRole("tab", { name: "Overview" }));
  expect(screen.getByText("Archive")).toBeInTheDocument();
  expect(screen.getByText("Local filesystem")).toBeInTheDocument();
  expect(screen.queryByText("localfs")).toBeNull();
  expect(screen.getByText("demo")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Name of the confirming person"), "Customer Rep");
  await userEvent.click(screen.getByRole("button", { name: "Record customer confirmation" }));
  expect(await screen.findByText(/Confirmed by Customer Rep on/)).toBeInTheDocument();
  const consentCall = f.calls.find((c) => c.method === "POST");
  expect(consentCall && JSON.parse(await consentCall.clone().text())).toEqual({
    confirmed_by_name: "Customer Rep",
  });
});

it("hides storage, gap report, members and settings from clients", async () => {
  mockFetch([
    {
      path: `/api/v1/projects/${PID}`,
      body: { ...base, my_role: "client", settings: null, storage: null },
    },
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: [] },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, customerMe).element);
  expect(await screen.findByRole("heading", { name: "Demo" })).toBeInTheDocument();
  for (const name of ["Gap report", "Members", "Settings"]) {
    expect(screen.queryByRole("tab", { name })).not.toBeInTheDocument();
  }
  await userEvent.click(screen.getByRole("tab", { name: "Overview" }));
  expect(screen.queryByText("Archive")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Name of the confirming person")).not.toBeInTheDocument();
  expect(screen.getByText(/Not confirmed yet/)).toBeInTheDocument();
});

it("shows the gap report tab to viewers but no settings", async () => {
  mockFetch([
    { path: `/api/v1/projects/${PID}`, body: { ...base, my_role: "viewer" } },
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: [] },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Demo" });
  expect(screen.getByRole("tab", { name: "Gap report" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Members" })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: "Settings" })).not.toBeInTheDocument();
});

it("reports an unknown project", async () => {
  mockFetch([
    { path: `/api/v1/projects/${PID}`, status: 404, body: { detail: "Project not found." } },
  ]);
  render(withSession(<ProjectPage projectId={PID} />, memberMe).element);
  expect(await screen.findByRole("alert")).toHaveTextContent("Project not found.");
});
