import { afterEach, expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { api, setUnauthorizedHandler } from "./client";

afterEach(() => setUnauthorizedHandler(null));

it("adds the CSRF header to non-GET requests only and sends JSON", async () => {
  const f = mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      body: { mfa_enrolled: false, must_change_password: true },
    },
    { path: "/api/v1/projects", body: [] },
  ]);
  const { data } = await api.POST("/api/v1/auth/login", {
    body: { email: "a@example.com", password: "pw" },
  });
  await api.GET("/api/v1/projects");
  expect(data?.must_change_password).toBe(true);
  expect(f.calls[0].headers.get("X-QC-Agent")).toBe("1");
  expect(f.calls[0].headers.get("content-type")).toBe("application/json");
  expect(f.calls[0].url).toBe("http://localhost:3000/api/v1/auth/login");
  expect(f.calls[1].headers.get("X-QC-Agent")).toBeNull();
});

it("fills path parameters", async () => {
  const f = mockFetch([{ path: "/api/v1/projects/abc", body: {} }]);
  await api.GET("/api/v1/projects/{project_id}", { params: { path: { project_id: "abc" } } });
  expect(new URL(f.calls[0].url).pathname).toBe("/api/v1/projects/abc");
});

it("test_401_outside_auth_calls_the_unauthorized_handler", async () => {
  mockFetch([{ path: "/api/v1/projects", status: 401, body: { detail: "Not authenticated." } }]);
  const handler = vi.fn();
  setUnauthorizedHandler(handler);
  const { data, response } = await api.GET("/api/v1/projects");
  expect(response.status).toBe(401);
  expect(data).toBeUndefined();
  expect(handler).toHaveBeenCalledTimes(1);
});

it("test_401_from_auth_endpoints_does_not_redirect", async () => {
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/auth/login",
      status: 401,
      body: { detail: "Invalid e-mail or password." },
    },
  ]);
  const handler = vi.fn();
  setUnauthorizedHandler(handler);
  const { error } = await api.POST("/api/v1/auth/login", {
    body: { email: "a@example.com", password: "wrong" },
  });
  expect((error as unknown as { detail: string }).detail).toBe("Invalid e-mail or password.");
  expect(handler).not.toHaveBeenCalled();
});

it("returns undefined data for 204 responses", async () => {
  mockFetch([{ method: "POST", path: "/api/v1/auth/logout", status: 204 }]);
  const { data, error, response } = await api.POST("/api/v1/auth/logout");
  expect(response.status).toBe(204);
  expect(data).toBeUndefined();
  expect(error).toBeUndefined();
});
