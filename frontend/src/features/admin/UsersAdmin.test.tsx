import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { UsersAdmin } from "./UsersAdmin";

const alice = {
  id: "u-alice",
  email: "alice@example.com",
  display_name: "Alice",
  account_type: "internal",
  is_admin: false,
  is_active: true,
  mfa_enabled: true,
  must_change_password: false,
  locked_until: null,
};

it("test_create_user_shows_the_temporary_password_once", async () => {
  const f = mockFetch([
    { path: "/api/v1/users", body: [alice] },
    {
      method: "POST",
      path: "/api/v1/users",
      status: 201,
      body: {
        user: { ...alice, id: "u-bob", email: "bob@example.com", display_name: "Bob" },
        temporary_password: "example-temporary-password",
      },
    },
  ]);
  render(<UsersAdmin />);
  expect(await screen.findByRole("cell", { name: "alice@example.com" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Create user" }));
  await userEvent.type(screen.getByLabelText("E-mail"), "bob@example.com");
  await userEvent.type(screen.getByLabelText("Display name"), "Bob");
  await userEvent.selectOptions(screen.getByLabelText("Account type"), "customer");
  expect(screen.getByLabelText("Administrator")).toBeDisabled(); // customers cannot be admins
  await userEvent.selectOptions(screen.getByLabelText("Account type"), "internal");
  await userEvent.click(screen.getByRole("button", { name: "Create" }));
  const dialog = await screen.findByRole("dialog", { name: "Temporary password" });
  expect(within(dialog).getByText("example-temporary-password")).toBeInTheDocument();
  expect(await f.body(1)).toEqual({
    email: "bob@example.com",
    display_name: "Bob",
    account_type: "internal",
    is_admin: false,
  });
  await userEvent.click(within(dialog).getByRole("button", { name: "Close" }));
  expect(screen.queryByText("example-temporary-password")).not.toBeInTheDocument();
  expect(f.find("GET", "/api/v1/users")).toBeDefined();
});

it("deactivates after confirmation and resets MFA", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const f = mockFetch([
    { path: "/api/v1/users", body: [alice] },
    { method: "PATCH", path: "/api/v1/users/u-alice", body: { ...alice, is_active: false } },
    { method: "POST", path: "/api/v1/users/u-alice/reset-mfa", status: 204 },
  ]);
  render(<UsersAdmin />);
  const row = (await screen.findByRole("cell", { name: "alice@example.com" })).closest("tr")!;
  await userEvent.click(within(row).getByRole("button", { name: "Deactivate" }));
  expect(await f.body(1)).toEqual({ is_active: false });
  await userEvent.click(within(row).getByRole("button", { name: "Reset MFA" }));
  expect(await screen.findByRole("status")).toHaveTextContent("MFA reset.");
  expect(f.find("POST", "/api/v1/users/u-alice/reset-mfa")).toBeDefined();
});
