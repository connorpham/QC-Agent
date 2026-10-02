import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { ConnectionDialog } from "./ConnectionDialog";

const created = {
  id: "c-new",
  type: "sharepoint",
  name: "Acme library",
  config: {},
  is_default: false,
  is_active: true,
  has_secret: true,
  created_at: "2026-10-02T10:00:00+00:00",
  updated_at: "2026-10-02T10:00:00+00:00",
};

function open() {
  const onSaved = vi.fn();
  render(<ConnectionDialog onClose={() => {}} onSaved={onSaved} />);
  return onSaved;
}

it("switches the fields when the type changes, inside the same dialog", async () => {
  open();
  expect(screen.getByLabelText("Root path")).toBeInTheDocument();
  await userEvent.selectOptions(screen.getByLabelText("Type"), "sharepoint");
  expect(screen.queryByLabelText("Root path")).toBeNull();
  for (const label of [
    "Tenant ID",
    "Client ID",
    "Client secret",
    "Site ID",
    "Document library (drive) ID",
  ]) {
    expect(screen.getByLabelText(label)).toBeInTheDocument();
  }
  await userEvent.selectOptions(screen.getByLabelText("Type"), "gdrive");
  expect(screen.queryByLabelText("Tenant ID")).toBeNull();
  expect(screen.getByLabelText("Shared Drive ID")).toBeInTheDocument();
  expect(screen.getByLabelText("Service account JSON key")).toBeInTheDocument();
  expect(screen.getAllByRole("dialog")).toHaveLength(1);
});

it("creates a SharePoint connection from typed fields only", async () => {
  const f = mockFetch([
    { method: "POST", path: "/api/v1/storage-connections", status: 201, body: created },
  ]);
  open();
  await userEvent.type(screen.getByLabelText("Name"), "Acme library");
  await userEvent.selectOptions(screen.getByLabelText("Type"), "sharepoint");
  await userEvent.type(screen.getByLabelText("Tenant ID"), "tenant-value");
  await userEvent.type(screen.getByLabelText("Client ID"), "client-value");
  await userEvent.type(screen.getByLabelText("Client secret"), "secret-value");
  await userEvent.type(screen.getByLabelText("Site ID"), "site-value");
  await userEvent.type(screen.getByLabelText("Document library (drive) ID"), "drive-value");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await f.body(0)).toEqual({
    type: "sharepoint",
    name: "Acme library",
    config: {
      tenant_id: "tenant-value",
      client_id: "client-value",
      site_id: "site-value",
      drive_id: "drive-value",
    },
    secret: "secret-value",
  });
});

it("keeps the secret out of the DOM after typing and never prefills it", async () => {
  open();
  await userEvent.selectOptions(screen.getByLabelText("Type"), "sharepoint");
  const secret = screen.getByLabelText("Client secret");
  await userEvent.type(secret, "secret-value");
  expect(secret).toHaveAttribute("type", "password");
  expect(secret).toHaveAttribute("autocomplete", "off");
  expect(document.body.innerHTML).not.toContain("secret-value");
});

it("requires the secret when creating a cloud connection", async () => {
  const f = mockFetch([]);
  open();
  await userEvent.type(screen.getByLabelText("Name"), "Acme drive");
  await userEvent.selectOptions(screen.getByLabelText("Type"), "gdrive");
  await userEvent.type(screen.getByLabelText("Shared Drive ID"), "0ATest");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Service account JSON key is required.",
  );
  expect(f.calls).toHaveLength(0);
});

it("lets an existing cloud connection be edited without re-entering the secret", async () => {
  const f = mockFetch([
    {
      method: "PATCH",
      path: "/api/v1/storage-connections/c-1",
      body: { ...created, id: "c-1" },
    },
  ]);
  render(
    <ConnectionDialog
      connection={{
        ...created,
        id: "c-1",
        config: {
          tenant_id: "t",
          client_id: "c",
          site_id: "s",
          drive_id: "d",
        },
      }}
      onClose={() => {}}
      onSaved={() => {}}
    />,
  );
  expect(screen.getByLabelText("Type")).toBeDisabled();
  expect(screen.getByLabelText("Client secret")).toHaveValue("");
  await userEvent.clear(screen.getByLabelText("Site ID"));
  await userEvent.type(screen.getByLabelText("Site ID"), "s2");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  const body = (await f.body(0)) as { secret?: string };
  expect(body.secret).toBeUndefined();
});
