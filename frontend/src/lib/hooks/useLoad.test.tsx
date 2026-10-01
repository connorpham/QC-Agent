import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { mockFetch } from "@/test/fetch-mock";
import { useLoad } from "./useLoad";

function Probe() {
  const projects = useLoad(() => api.GET("/api/v1/projects").then((r) => unwrap(r)), []);
  if (projects.loading) return <p role="status">loading</p>;
  if (projects.error) return <p role="alert">{projects.error}</p>;
  return <p>{projects.data?.length ?? 0} projects</p>;
}

it("exposes loading, then data", async () => {
  mockFetch([{ path: "/api/v1/projects", body: [{ id: "p1" }] }]);
  render(<Probe />);
  expect(screen.getByRole("status")).toHaveTextContent("loading");
  expect(await screen.findByText("1 projects")).toBeInTheDocument();
});

it("exposes the API error message", async () => {
  mockFetch([
    { path: "/api/v1/projects", status: 503, body: { detail: "Storage is unavailable." } },
  ]);
  render(<Probe />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Storage is unavailable.");
});
