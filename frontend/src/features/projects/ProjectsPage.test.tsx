import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { customerMe, memberMe, withSession } from "@/test/session";
import { ProjectsPage } from "./ProjectsPage";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

const project = {
  id: "11111111-1111-1111-1111-111111111111",
  slug: "demo",
  name: "Demo",
  client_name: "ACME",
  created_at: "2026-10-01T10:00:00+00:00",
  my_role: "owner",
  settings: null,
  storage: null,
  llm_consent: null,
};

it("lists projects with a link and offers creation to internal users", async () => {
  mockFetch([{ path: "/api/v1/projects", body: [project] }]);
  render(withSession(<ProjectsPage />, memberMe).element);
  expect(await screen.findByRole("link", { name: "Demo" })).toHaveAttribute(
    "href",
    "/projects/11111111-1111-1111-1111-111111111111",
  );
  expect(screen.getByText("ACME")).toBeInTheDocument();
  expect(screen.getByText("Owner")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "New project" })).toBeInTheDocument();
});

it("shows an empty state and no create button to customers", async () => {
  mockFetch([{ path: "/api/v1/projects", body: [] }]);
  render(withSession(<ProjectsPage />, customerMe).element);
  expect(await screen.findByText("You are not a member of any project yet.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "New project" })).not.toBeInTheDocument();
});
