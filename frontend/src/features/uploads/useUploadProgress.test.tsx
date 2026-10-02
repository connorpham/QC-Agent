import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { FakeEventSource } from "@/test/fake-event-source";
import { useUploadProgress } from "./useUploadProgress";

const UID = "22222222-2222-2222-2222-222222222222";
const item = (status: string, overrides: Record<string, unknown> = {}) => ({
  id: "i1",
  upload_id: UID,
  original_name: "srs.docx",
  ext: "docx",
  size: 10,
  sha256: "x",
  selected_doc_type: "srs",
  final_doc_type: null,
  title: "SRS",
  intent: "new",
  target_document_id: null,
  visibility: "internal",
  status,
  type_check: null,
  check_explanation: null,
  suggested_doc_type: null,
  version_hint_document_id: null,
  warnings: [],
  conversion_meta: {},
  error: null,
  document_id: null,
  created_at: "2026-10-02T09:00:00+00:00",
  updated_at: "2026-10-02T09:00:00+00:00",
  ...overrides,
});
const uploadWith = (status: string, overrides: Record<string, unknown> = {}) => ({
  id: UID,
  project_id: "p1",
  uploaded_by: "me",
  created_at: "2026-10-02T09:00:00+00:00",
  rejected: [],
  items: [item(status, overrides)],
});

function Probe({ pollIntervalMs }: { pollIntervalMs?: number }) {
  const progress = useUploadProgress(UID, { pollIntervalMs });
  if (progress.error) return <p role="alert">{progress.error}</p>;
  if (!progress.upload) return <p role="status">loading</p>;
  return (
    <div>
      <p data-testid="status">{progress.upload.items[0].status}</p>
      <p data-testid="connection">{progress.connection}</p>
      <p data-testid="doc">{progress.upload.items[0].document_id ?? "-"}</p>
    </div>
  );
}

beforeEach(() => FakeEventSource.install());

/** The EventSource is created in an effect after the upload loads; wait for it. */
async function lastSource(): Promise<FakeEventSource> {
  await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
  return FakeEventSource.last;
}

it("loads the upload, subscribes while items are active, applies events and refreshes on settled", async () => {
  let serverStatus = "converting";
  const f = mockFetch([
    {
      path: `/api/v1/uploads/${UID}`,
      handler: () =>
        uploadWith(serverStatus, serverStatus === "published" ? { document_id: "d1" } : {}),
    },
  ]);
  render(<Probe />);
  expect(await screen.findByTestId("status")).toHaveTextContent("converting");
  const source = await lastSource();
  expect(source.url).toBe(`/api/v1/uploads/${UID}/events`);
  act(() => source.open());
  expect(screen.getByTestId("connection")).toHaveTextContent("live");
  act(() => source.emit("item.status", { item_id: "i1", status: "checking" }, "1"));
  expect(screen.getByTestId("status")).toHaveTextContent("checking");
  act(() => source.emit("item.status", { item_id: "i1", status: "publishing" }, "2"));
  serverStatus = "published";
  act(() => source.emit("upload.settled", { upload_id: UID, last_event_id: 2 }));
  expect(source.closed).toBe(true);
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("published"));
  expect(screen.getByTestId("doc")).toHaveTextContent("d1");
  expect(screen.getByTestId("connection")).toHaveTextContent("closed");
  expect(f.calls.filter((c) => new URL(c.url).pathname === `/api/v1/uploads/${UID}`)).toHaveLength(
    2,
  );
});

it("does not subscribe when nothing is active any more", async () => {
  mockFetch([
    { path: `/api/v1/uploads/${UID}`, body: uploadWith("published", { document_id: "d1" }) },
  ]);
  render(<Probe />);
  expect(await screen.findByTestId("status")).toHaveTextContent("published");
  expect(FakeEventSource.instances).toHaveLength(0);
  expect(screen.getByTestId("connection")).toHaveTextContent("closed");
});

it("reconnects with the browser's Last-Event-ID and applies each event once", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, body: uploadWith("converting") }]);
  render(<Probe />);
  await screen.findByTestId("status");
  const source = await lastSource();
  act(() => source.open());
  act(() => source.emit("item.status", { item_id: "i1", status: "checking" }, "7"));
  // the browser retries by itself: an error with readyState CONNECTING, then open again, then
  // the replay resumes after id 7 — the hook keeps the same EventSource (it carries the id)
  act(() => source.fail(FakeEventSource.CONNECTING));
  expect(screen.getByTestId("connection")).toHaveTextContent("reconnecting");
  expect(source.closed).toBe(false);
  act(() => source.open());
  expect(screen.getByTestId("connection")).toHaveTextContent("live");
  act(() => source.emit("item.status", { item_id: "i1", status: "checking" }, "7"));
  act(() => source.emit("item.status", { item_id: "i1", status: "publishing" }, "8"));
  expect(screen.getByTestId("status")).toHaveTextContent("publishing");
  expect(FakeEventSource.instances).toHaveLength(1);
});

it("falls back to polling when the browser gives up on the stream", async () => {
  let serverStatus = "converting";
  mockFetch([{ path: `/api/v1/uploads/${UID}`, handler: () => uploadWith(serverStatus) }]);
  render(<Probe pollIntervalMs={20} />);
  expect(await screen.findByTestId("status")).toHaveTextContent("converting");
  const source = await lastSource();
  act(() => source.fail(FakeEventSource.CLOSED));
  expect(screen.getByTestId("connection")).toHaveTextContent("polling");
  expect(source.closed).toBe(true);
  serverStatus = "published"; // the next poll (20 ms) sees it
  await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("published"));
  expect(screen.getByTestId("connection")).toHaveTextContent("closed");
});

it("reopens the stream when the refresh after settled still shows active items", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, body: uploadWith("publishing") }]);
  render(<Probe />);
  await screen.findByTestId("status");
  const first = await lastSource();
  act(() => first.open());
  act(() => first.emit("upload.settled", { upload_id: UID, last_event_id: 3 }));
  await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
  expect(first.closed).toBe(true);
  expect(FakeEventSource.last.closed).toBe(false);
});

it("shows not found for an upload the user may not see", async () => {
  mockFetch([
    { path: `/api/v1/uploads/${UID}`, status: 404, body: { detail: "Upload not found." } },
  ]);
  render(<Probe />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Upload not found.");
  expect(FakeEventSource.instances).toHaveLength(0);
});

it("applies a snapshot item.status frame that carries no id (sent on connect and reconnect)", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, body: uploadWith("converting") }]);
  render(<Probe />);
  await screen.findByTestId("status");
  const source = await lastSource();
  act(() => source.open());
  // no third argument: the fake dispatches a MessageEvent with an empty lastEventId, just like
  // the server's snapshot-on-connect frame (which deliberately carries no `id:` line)
  act(() => source.emit("item.status", { item_id: "i1", status: "checking" }));
  expect(screen.getByTestId("status")).toHaveTextContent("checking");
});

it("clears the polling interval on unmount so it cannot leak", async () => {
  // Fake timers only for this test; restored in the `finally` below so no other test in this
  // file (or any other) sees them.
  vi.useFakeTimers({ shouldAdvanceTime: true });
  try {
    const f = mockFetch([{ path: `/api/v1/uploads/${UID}`, body: uploadWith("converting") }]);
    const { unmount } = render(<Probe pollIntervalMs={20} />);
    await waitFor(() => expect(screen.getByTestId("status")).toHaveTextContent("converting"));
    const source = await lastSource();
    act(() => source.fail(FakeEventSource.CLOSED)); // the browser gave up: polling starts
    await waitFor(() => expect(screen.getByTestId("connection")).toHaveTextContent("polling"));
    const callsAtUnmount = f.calls.length;
    unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(20 * 10); // several poll intervals' worth
    });
    expect(f.calls.length).toBe(callsAtUnmount); // no request fired after unmount
  } finally {
    vi.useRealTimers();
  }
});

it("applies the final item states carried on upload.settled, ahead of the refetch", async () => {
  let serverStatus = "converting";
  mockFetch([
    {
      path: `/api/v1/uploads/${UID}`,
      handler: () =>
        uploadWith(serverStatus, serverStatus === "published" ? { document_id: "d9" } : {}),
    },
  ]);
  render(<Probe />);
  await screen.findByTestId("status");
  const source = await lastSource();
  act(() => source.open());
  serverStatus = "published"; // the refetch triggered by upload.settled will see this too
  act(() =>
    source.emit("upload.settled", {
      upload_id: UID,
      last_event_id: 5,
      items: [{ item_id: "i1", status: "published", document_id: "d9" }],
    }),
  );
  // applied synchronously from the event, ahead of the refetch (which lands on the same state)
  expect(screen.getByTestId("status")).toHaveTextContent("published");
  expect(screen.getByTestId("doc")).toHaveTextContent("d9");
  await waitFor(() => expect(screen.getByTestId("connection")).toHaveTextContent("closed"));
});
