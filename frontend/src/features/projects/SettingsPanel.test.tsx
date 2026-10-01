import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { SettingsPanel } from "./SettingsPanel";

const PID = "11111111-1111-1111-1111-111111111111";
const project = {
  id: PID,
  slug: "demo",
  name: "Demo",
  client_name: "ACME",
  created_at: "2026-10-01T10:00:00+00:00",
  my_role: "owner",
  settings: { model: "claude-opus-5", check_budget_usd: 1, normalize_budget_usd: 2 },
  storage: null,
  llm_consent: null,
};

it("patches name, client and settings", async () => {
  const updated = {
    ...project,
    name: "Demo 2",
    settings: { ...project.settings, check_budget_usd: 0.5 },
  };
  const f = mockFetch([{ method: "PATCH", path: `/api/v1/projects/${PID}`, body: updated }]);
  const onUpdated = vi.fn();
  render(<SettingsPanel project={project} onUpdated={onUpdated} />);
  const name = screen.getByLabelText("Project name");
  await userEvent.clear(name);
  await userEvent.type(name, "Demo 2");
  const budget = screen.getByLabelText("Type-check budget (USD)");
  await userEvent.clear(budget);
  await userEvent.type(budget, "0.5");
  await userEvent.click(screen.getByRole("button", { name: "Save settings" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Settings saved.");
  expect(await f.body(0)).toEqual({
    name: "Demo 2",
    client_name: "ACME",
    settings: { model: "claude-opus-5", check_budget_usd: 0.5, normalize_budget_usd: 2 },
  });
  expect(onUpdated).toHaveBeenCalledWith(updated);
});
