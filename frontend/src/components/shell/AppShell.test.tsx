import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { adminMe, memberMe } from "@/test/session";
import { SessionProvider } from "@/lib/session/SessionProvider";
import { AppShell } from "./AppShell";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/projects",
}));

function renderShell() {
  return render(
    <SessionProvider>
      <AppShell>
        <p>Page content</p>
      </AppShell>
    </SessionProvider>,
  );
}

it("shows the user, the role badge and the admin link for administrators", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: adminMe }]);
  renderShell();
  expect(await screen.findByText("Page content")).toBeInTheDocument();
  expect(screen.getByText("Root")).toBeInTheDocument();
  expect(screen.getByText("Administrator")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Admin" })).toHaveAttribute("href", "/admin/users");
  expect(screen.getByRole("link", { name: "Projects" })).toHaveAttribute("aria-current", "page");
});

it("hides the admin link from team members and logs out", async () => {
  const f = mockFetch([
    { path: "/api/v1/auth/me", body: memberMe },
    { method: "POST", path: "/api/v1/auth/logout", status: 204 },
  ]);
  renderShell();
  expect(await screen.findByText("Team member")).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Admin" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Log out" }));
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  expect(f.find("POST", "/api/v1/auth/logout")).toBeDefined();
});
