import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { ChangePasswordForm } from "./ChangePasswordForm";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

async function fill(current: string, next: string, confirm: string) {
  await userEvent.type(screen.getByLabelText("Current password"), current);
  await userEvent.type(screen.getByLabelText("New password"), next);
  await userEvent.type(screen.getByLabelText("Confirm new password"), confirm);
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
}

it("refuses mismatching passwords without calling the API", async () => {
  const f = mockFetch([]);
  render(<ChangePasswordForm onChanged={vi.fn()} />);
  await fill("temp-password-123", "new-password-abcdef", "new-password-abcdeg");
  expect(await screen.findByRole("alert")).toHaveTextContent("The new passwords do not match.");
  expect(f.fn).not.toHaveBeenCalled();
});

it("submits and reports success, or shows every policy message", async () => {
  const f = mockFetch([{ method: "POST", path: "/api/v1/auth/change-password", status: 204 }]);
  const onChanged = vi.fn();
  render(<ChangePasswordForm onChanged={onChanged} />);
  await fill("temp-password-123", "new-password-abcdef", "new-password-abcdef");
  expect(await f.body(0)).toEqual({
    current_password: "temp-password-123",
    new_password: "new-password-abcdef",
  });
  expect(onChanged).toHaveBeenCalled();
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/change-password",
      status: 400,
      body: { detail: ["Use at least 12 characters.", "Current password is incorrect."] },
    },
  ]);
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Use at least 12 characters. Current password is incorrect.",
  );
});

it("sends the user to /login on a 401 (Controller Ruling A2: the client's 401 redirect handler skips /auth/* paths)", async () => {
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/change-password",
      status: 401,
      body: { detail: "Not authenticated." },
    },
  ]);
  const onChanged = vi.fn();
  render(<ChangePasswordForm onChanged={onChanged} />);
  await fill("temp-password-123", "new-password-abcdef", "new-password-abcdef");
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(onChanged).not.toHaveBeenCalled();
});
