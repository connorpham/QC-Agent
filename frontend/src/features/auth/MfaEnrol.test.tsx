import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { adminMe } from "@/test/session";
import { MfaEnrol } from "./MfaEnrol";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }) }));

beforeEach(() => replace.mockClear());

vi.mock("qrcode", () => ({
  default: { toDataURL: vi.fn().mockResolvedValue("data:image/png;base64,QR") },
}));

const CODES = Array.from({ length: 10 }, (_, i) => `0000000${i}-abcdef0${i}`);

function routes(confirmStatus = 200) {
  return mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/mfa/enroll",
      body: {
        secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
        otpauth_uri:
          "otpauth://totp/QC-Agent:a%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=QC-Agent",
      },
    },
    {
      method: "POST",
      path: "/api/v1/auth/mfa/confirm",
      status: confirmStatus,
      body: confirmStatus === 200 ? { recovery_codes: CODES } : { detail: "Invalid code." },
    },
    { path: "/api/v1/auth/me", body: adminMe },
  ]);
}

it("shows the QR code and setup key, confirms the code and reveals the recovery codes once", async () => {
  const f = routes();
  const onDone = vi.fn();
  render(<MfaEnrol onDone={onDone} />);
  expect(await screen.findByAltText("QR code for your authenticator app")).toHaveAttribute(
    "src",
    "data:image/png;base64,QR",
  );
  expect(screen.getByLabelText("Setup key (if you cannot scan)")).toHaveValue(
    "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
  );
  await userEvent.type(screen.getByLabelText("Authentication code"), "123456");
  await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(await screen.findByRole("heading", { name: "Recovery codes" })).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(10);
  expect(await f.body(1)).toEqual({ code: "123456" });
  // test_continue_is_disabled_until_the_codes_are_acknowledged
  const next = screen.getByRole("button", { name: "Continue" });
  expect(next).toBeDisabled();
  await userEvent.click(screen.getByLabelText("I have saved my recovery codes"));
  expect(next).toBeEnabled();
  await userEvent.click(next);
  expect(onDone).toHaveBeenCalledWith(adminMe);
});

it("shows the backend message for a wrong code and stays on the scan step", async () => {
  routes(400);
  render(<MfaEnrol onDone={vi.fn()} />);
  await userEvent.type(await screen.findByLabelText("Authentication code"), "000000");
  await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid code.");
  expect(screen.queryByRole("heading", { name: "Recovery codes" })).not.toBeInTheDocument();
});

it("enrols once per mount under React StrictMode", async () => {
  const f = routes();
  render(
    <StrictMode>
      <MfaEnrol onDone={vi.fn()} />
    </StrictMode>,
  );
  await screen.findByLabelText("Authentication code");
  const enrolments = f.calls.filter(
    (c) => c.method === "POST" && new URL(c.url).pathname === "/api/v1/auth/mfa/enroll",
  );
  expect(enrolments).toHaveLength(1);
});

it("sends the user to /login when the enrolment request finds no session", async () => {
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/mfa/enroll",
      status: 401,
      body: { detail: "Not authenticated." },
    },
  ]);
  render(<MfaEnrol onDone={vi.fn()} />);
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(screen.queryByRole("alert")).toBeNull();
});

it("sends the user to /login when the session dies before the code is confirmed", async () => {
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/mfa/enroll",
      body: {
        secret: "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP",
        otpauth_uri:
          "otpauth://totp/QC-Agent:a%40example.com?secret=JBSWY3DPEHPK3PXP&issuer=QC-Agent",
      },
    },
    {
      method: "POST",
      path: "/api/v1/auth/mfa/confirm",
      status: 401,
      body: { detail: "Not authenticated." },
    },
  ]);
  render(<MfaEnrol onDone={vi.fn()} />);
  await userEvent.type(await screen.findByLabelText("Authentication code"), "123456");
  await userEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(screen.queryByRole("heading", { name: "Recovery codes" })).toBeNull();
});
