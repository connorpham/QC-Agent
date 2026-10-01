import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { memberMe } from "@/test/session";
import { MfaVerify } from "./MfaVerify";

it("rejects a wrong code, then verifies a right one", async () => {
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/mfa/verify",
      status: 401,
      body: { detail: "Invalid code." },
    },
  ]);
  const onVerified = vi.fn();
  render(<MfaVerify onVerified={onVerified} />);
  const input = screen.getByLabelText("Authentication or recovery code");
  await userEvent.type(input, "000000");
  await userEvent.click(screen.getByRole("button", { name: "Verify" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid code.");
  expect(onVerified).not.toHaveBeenCalled();
  const f = mockFetch([{ method: "POST", path: "/api/v1/auth/mfa/verify", body: memberMe }]);
  await userEvent.clear(input);
  await userEvent.type(input, "1a2b3c4d-5e6f7a8b");
  await userEvent.click(screen.getByRole("button", { name: "Verify" }));
  expect(await f.body(0)).toEqual({ code: "1a2b3c4d-5e6f7a8b" });
  expect(onVerified).toHaveBeenCalledWith(memberMe);
});
