import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { LoginForm } from "./LoginForm";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

async function fillAndSubmit(email: string, password: string) {
  await userEvent.type(screen.getByLabelText("E-mail"), email);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

it("posts the credentials and continues to the MFA step", async () => {
  const f = mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      body: { mfa_enrolled: false, must_change_password: true },
    },
  ]);
  render(<LoginForm />);
  await fillAndSubmit("alice@example.com", "correct-horse-battery-staple");
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/mfa"));
  expect(await f.body(0)).toEqual({
    email: "alice@example.com",
    password: "correct-horse-battery-staple",
  });
});

it("shows the backend's message for wrong credentials and for rate limiting", async () => {
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      status: 401,
      body: { detail: "Invalid e-mail or password." },
    },
  ]);
  render(<LoginForm />);
  await fillAndSubmit("alice@example.com", "wrong");
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid e-mail or password.");
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      status: 429,
      body: { detail: "Too many attempts. Try again later." },
    },
  ]);
  await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts. Try again later.");
  expect(replace).not.toHaveBeenCalled();
});
