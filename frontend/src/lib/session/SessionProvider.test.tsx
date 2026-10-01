import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { adminMe } from "@/test/session";
import { SessionProvider, useSession } from "./SessionProvider";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/projects",
}));

function WhoAmI() {
  const { me } = useSession();
  return <p>Signed in as {me.display_name}</p>;
}

it("renders children once /auth/me reports a complete session", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: adminMe }]);
  render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  expect(screen.getByRole("status")).toHaveTextContent("Loading…");
  expect(await screen.findByText("Signed in as Root")).toBeInTheDocument();
  expect(replace).not.toHaveBeenCalled();
});

it("sends anonymous users to /login", async () => {
  mockFetch([{ path: "/api/v1/auth/me", status: 401, body: { detail: "Not authenticated." } }]);
  render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(screen.queryByText(/Signed in/)).not.toBeInTheDocument();
});

it("sends MFA-pending sessions to /mfa and password changes to /change-password", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: { ...adminMe, mfa_verified: false } }]);
  const first = render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/mfa"));
  first.unmount();
  mockFetch([{ path: "/api/v1/auth/me", body: { ...adminMe, must_change_password: true } }]);
  render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/change-password"));
});

it("shows a retry when /auth/me fails for another reason", async () => {
  mockFetch([{ path: "/api/v1/auth/me", status: 503, body: { detail: "down" } }]);
  render(
    <SessionProvider>
      <WhoAmI />
    </SessionProvider>,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not load data. Try again.");
  expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
});
