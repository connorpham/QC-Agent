import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { memberMe } from "@/test/session";
import { MfaPage } from "./MfaPage";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));
vi.mock("qrcode", () => ({ default: { toDataURL: vi.fn().mockResolvedValue("data:,qr") } }));

it("offers enrolment when MFA is not enabled yet", async () => {
  mockFetch([
    { path: "/api/v1/auth/me", body: { ...memberMe, mfa_enabled: false, mfa_verified: false } },
    {
      method: "POST",
      path: "/api/v1/auth/mfa/enroll",
      body: { secret: "S", otpauth_uri: "otpauth://x" },
    },
  ]);
  render(<MfaPage />);
  expect(await screen.findByLabelText("Setup key (if you cannot scan)")).toHaveValue("S");
});

it("asks for a code when MFA is enabled", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: { ...memberMe, mfa_verified: false } }]);
  render(<MfaPage />);
  expect(await screen.findByLabelText("Authentication or recovery code")).toBeInTheDocument();
});

it("skips ahead when the session is already verified, and to /login when anonymous", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: { ...memberMe, must_change_password: true } }]);
  const first = render(<MfaPage />);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/change-password"));
  first.unmount();
  mockFetch([{ path: "/api/v1/auth/me", status: 401, body: { detail: "Not authenticated." } }]);
  render(<MfaPage />);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
});
