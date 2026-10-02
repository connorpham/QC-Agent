import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { setUnauthorizedHandler } from "@/lib/api/client";
import { FakeXHR } from "@/test/fake-xhr";
import { uploadMultipart } from "./upload";

beforeEach(() => FakeXHR.install());
afterEach(() => setUnauthorizedHandler(null));

function form() {
  const fd = new FormData();
  fd.append("files", new File(["abc"], "a.md", { type: "text/markdown" }), "a.md");
  fd.append("items", JSON.stringify([{ doc_type: "srs" }]));
  return fd;
}

it("posts the form with the CSRF header, reports progress and returns the parsed body", async () => {
  FakeXHR.respondWith = { status: 201, body: { id: "u1", items: [] } };
  const progress: number[] = [];
  const result = await uploadMultipart<{ id: string }>("/api/v1/projects/p1/uploads", form(), (f) =>
    progress.push(f),
  );
  expect(result).toEqual({ ok: true, status: 201, data: { id: "u1", items: [] } });
  const sent = FakeXHR.instances[0];
  expect(sent.method).toBe("POST");
  expect(sent.url).toBe("/api/v1/projects/p1/uploads");
  expect(sent.headers["X-QC-Agent"]).toBe("1");
  expect(sent.headers["Accept"]).toBe("application/json");
  expect((sent.body as FormData).getAll("files").map((f) => (f as File).name)).toEqual(["a.md"]);
  expect(progress).toEqual([0.5]);
});

it("returns the error body for non-2xx responses and notifies on 401", async () => {
  FakeXHR.respondWith = { status: 409, body: { detail: "Consent required." } };
  const conflict = await uploadMultipart("/api/v1/projects/p1/uploads", form());
  expect(conflict).toEqual({ ok: false, status: 409, error: { detail: "Consent required." } });
  const handler = vi.fn();
  setUnauthorizedHandler(handler);
  FakeXHR.respondWith = { status: 401, body: { detail: "Not authenticated." } };
  const unauthorized = await uploadMultipart("/api/v1/projects/p1/uploads", form());
  expect(unauthorized.ok).toBe(false);
  expect(handler).toHaveBeenCalledTimes(1);
});

it("rejects with the generic request error on a network failure", async () => {
  FakeXHR.failWithNetworkError = true;
  await expect(uploadMultipart("/api/v1/projects/p1/uploads", form())).rejects.toThrow(
    "The request failed. Try again.",
  );
});
