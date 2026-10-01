import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { CreateProjectDialog } from "./CreateProjectDialog";

const connections = [
  { id: "c-archive", name: "Archive", type: "localfs", is_default: false },
  { id: "c-default", name: "Local storage", type: "localfs", is_default: true },
];

it("preselects the default connection and posts the chosen values", async () => {
  const f = mockFetch([
    { path: "/api/v1/storage-connections/available", body: connections },
    { method: "POST", path: "/api/v1/projects", status: 201, body: { id: "p1", name: "Portal" } },
  ]);
  const onCreated = vi.fn();
  render(<CreateProjectDialog onClose={vi.fn()} onCreated={onCreated} />);
  const select = await screen.findByLabelText("Storage connection");
  expect(select).toHaveValue("c-default");
  await userEvent.type(screen.getByLabelText("Project name"), "Portal");
  await userEvent.type(screen.getByLabelText("Client name"), "ACME");
  await userEvent.selectOptions(select, "c-archive");
  await userEvent.type(screen.getByLabelText("Root folder (optional)"), "portal-2026");
  await userEvent.click(screen.getByRole("button", { name: "Create project" }));
  expect(await f.body(1)).toEqual({
    name: "Portal",
    client_name: "ACME",
    storage_connection_id: "c-archive",
    storage_root: "portal-2026",
  });
  expect(onCreated).toHaveBeenCalledWith({ id: "p1", name: "Portal" });
});

it("shows the backend's validation message", async () => {
  mockFetch([
    { path: "/api/v1/storage-connections/available", body: connections },
    {
      method: "POST",
      path: "/api/v1/projects",
      status: 422,
      body: {
        detail: "This root folder is already used by another project on the selected connection.",
      },
    },
  ]);
  render(<CreateProjectDialog onClose={vi.fn()} onCreated={vi.fn()} />);
  await userEvent.type(await screen.findByLabelText("Project name"), "Portal");
  await userEvent.click(screen.getByRole("button", { name: "Create project" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("already used by another project");
  expect(screen.getByText("What is the LLM data-processing confirmation?")).toBeInTheDocument();
});
