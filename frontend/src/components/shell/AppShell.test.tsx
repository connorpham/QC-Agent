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
  expect(screen.getByRole("link", { name: "My tasks" })).toHaveAttribute("href", "/tasks");
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

it("collapses the navigation behind a menu button on small screens", async () => {
  mockFetch([{ path: "/api/v1/auth/me", body: memberMe }]);
  renderShell();
  await screen.findByText("Page content");
  const button = screen.getByRole("button", { name: "Open menu" });
  const menu = document.getElementById(button.getAttribute("aria-controls") ?? "");
  expect(menu).not.toBeNull();
  expect(button).toHaveAttribute("aria-expanded", "false");
  expect(menu).toHaveClass("hidden"); // Tailwind hides it below md; md:flex shows it again
  await userEvent.click(button);
  expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
  expect(menu).not.toHaveClass("hidden");
  await userEvent.click(screen.getByRole("link", { name: "Projects" }));
  expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute(
    "aria-expanded",
    "false",
  );
});
