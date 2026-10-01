import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { StorageAdmin } from "./StorageAdmin";

const local = {
  id: "c-local",
  type: "localfs",
  name: "Local storage",
  config: { root_path: "." },
  is_default: true,
  is_active: true,
  has_secret: false,
  created_at: "2026-10-01T10:00:00+00:00",
  updated_at: "2026-10-01T10:00:00+00:00",
};
const archive = {
  ...local,
  id: "c-archive",
  name: "Archive",
  config: { root_path: "archive" },
  is_default: false,
};

it("lists connections, creates a localfs connection and tests it", async () => {
  const f = mockFetch([
    { path: "/api/v1/storage-connections", body: [archive, local] },
    {
      method: "POST",
      path: "/api/v1/storage-connections",
      status: 201,
      body: { ...archive, id: "c-new", name: "E2E" },
    },
    {
      method: "POST",
      path: "/api/v1/storage-connections/c-archive/test",
      body: { ok: true, detail: "ok" },
    },
  ]);
  render(<StorageAdmin />);
  const localNameCell = await screen.findByRole("cell", { name: "Local storage" });
  const localRow = localNameCell.closest("tr")!;
  // The default indicator lives in the status cell, not the name cell, and must stay in the
  // accessibility tree (not aria-hidden) so a screen-reader user hears that this is the default.
  expect(within(localRow).getByRole("cell", { name: /Default/ })).toBeInTheDocument();
  expect(within(localRow).getByText("Default")).toBeInTheDocument();
  expect(within(localRow).queryByRole("button", { name: "Set as default" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "New connection" }));
  await userEvent.type(screen.getByLabelText("Name"), "E2E");
  expect(screen.queryByLabelText("Secret (write-only)")).toBeNull(); // hidden for localfs
  const rootPath = screen.getByLabelText("Root path");
  await userEvent.clear(rootPath);
  await userEvent.type(rootPath, "e2e");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await f.body(1)).toEqual({ type: "localfs", name: "E2E", config: { root_path: "e2e" } });
  expect(await screen.findByRole("status")).toHaveTextContent("Connection saved.");
  const archiveRow = screen.getByRole("cell", { name: "Archive" }).closest("tr")!;
  await userEvent.click(within(archiveRow).getByRole("button", { name: "Test connection" }));
  expect(await within(archiveRow).findByRole("status")).toHaveTextContent("Connection OK");
});

it("sets a default and shows a 409 when deactivation is refused", async () => {
  const f = mockFetch([
    { path: "/api/v1/storage-connections", body: [archive, local] },
    {
      method: "PATCH",
      path: "/api/v1/storage-connections/c-archive",
      body: { ...archive, is_default: true },
    },
    {
      method: "PATCH",
      path: "/api/v1/storage-connections/c-local",
      status: 409,
      body: {
        detail:
          "The default connection cannot be deactivated. Set another connection as the default first.",
      },
    },
  ]);
  render(<StorageAdmin />);
  const archiveRow = (await screen.findByRole("cell", { name: "Archive" })).closest("tr")!;
  await userEvent.click(within(archiveRow).getByRole("button", { name: "Set as default" }));
  expect(await f.body(1)).toEqual({ is_default: true });
  const localRow = screen.getByRole("cell", { name: "Local storage" }).closest("tr")!;
  await userEvent.click(within(localRow).getByRole("button", { name: "Deactivate" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("cannot be deactivated");
});
