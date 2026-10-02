import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { FakeEventSource } from "@/test/fake-event-source";
import { memberMe, withSession } from "@/test/session";
import { UploadProgress } from "./UploadProgress";

const UID = "22222222-2222-2222-2222-222222222222";
const PID = "11111111-1111-1111-1111-111111111111";
const base = {
  upload_id: UID,
  ext: "docx",
  size: 2048,
  sha256: "x",
  final_doc_type: null,
  intent: "new",
  target_document_id: null,
  visibility: "internal",
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
};
const upload = {
  id: UID,
  project_id: PID,
  uploaded_by: "me",
  created_at: "2026-10-02T09:00:00+00:00",
  rejected: [],
  items: [
    {
      ...base,
      id: "i1",
      original_name: "srs.docx",
      selected_doc_type: "srs",
      title: "SRS",
      status: "converting",
    },
    {
      ...base,
      id: "i2",
      original_name: "plan.docx",
      selected_doc_type: "srs",
      title: "Plan",
      status: "needs_confirmation",
      check_explanation: "Reads like a test plan.",
      suggested_doc_type: "test-plan",
    },
    {
      ...base,
      id: "i3",
      original_name: "broken.docx",
      selected_doc_type: "brd",
      title: "Broken",
      status: "failed",
      error: "File content does not match its extension.",
    },
    {
      ...base,
      id: "i4",
      original_name: "scan.pdf",
      ext: "pdf",
      selected_doc_type: "deploy-guide",
      title: "Scan",
      status: "published",
      type_check: "skipped",
      document_id: "d4",
      warnings: ["low_text"],
    },
  ],
};

beforeEach(() => FakeEventSource.install());

async function lastSource(): Promise<FakeEventSource> {
  await waitFor(() => expect(FakeEventSource.instances.length).toBeGreaterThan(0));
  return FakeEventSource.last;
}

it("lists every file with its status, explanations, links and the live indicator", async () => {
  mockFetch([{ path: `/api/v1/uploads/${UID}`, body: upload }]);
  render(withSession(<UploadProgress uploadId={UID} />, memberMe).element);
  expect(await screen.findByRole("heading", { name: "Upload progress" })).toBeInTheDocument();
  const rows = screen.getAllByRole("listitem");
  expect(rows).toHaveLength(4);
  expect(within(rows[0]).getByText("Converting")).toBeInTheDocument();
  expect(within(rows[1]).getByText("Needs confirmation")).toBeInTheDocument();
  expect(within(rows[1]).getByText("Reads like a test plan.")).toBeInTheDocument();
  expect(within(rows[1]).getByRole("link", { name: "Confirm in My tasks" })).toHaveAttribute(
    "href",
    "/tasks",
  );
  expect(within(rows[2]).getByText("Failed")).toBeInTheDocument();
  expect(
    within(rows[2]).getByText("File content does not match its extension."),
  ).toBeInTheDocument();
  expect(within(rows[2]).getByRole("button", { name: "Retry" })).toBeInTheDocument();
  expect(within(rows[3]).getByText("Published")).toBeInTheDocument();
  expect(within(rows[3]).getByRole("link", { name: "Open document" })).toHaveAttribute(
    "href",
    "/documents/d4",
  );
  expect(within(rows[3]).getByText(/Little extractable text/)).toBeInTheDocument();
  expect(within(rows[3]).getByText("Type check skipped")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Back to project" })).toHaveAttribute(
    "href",
    `/projects/${PID}`,
  );
  const source = await lastSource();
  act(() => source.open());
  expect(screen.getByRole("status", { name: "Connection" })).toHaveTextContent("Live");
});

it("updates a row from an event and retries a failed item", async () => {
  let retried = false; // the page reloads the upload after the retry
  const retriedItem = { ...upload.items[2], status: "uploaded", error: null };
  const f = mockFetch([
    {
      path: `/api/v1/uploads/${UID}`,
      handler: () =>
        retried
          ? { ...upload, items: [upload.items[0], upload.items[1], retriedItem, upload.items[3]] }
          : upload,
    },
    {
      method: "POST",
      path: "/api/v1/upload-items/i3/retry",
      handler: () => {
        retried = true;
        return retriedItem;
      },
    },
  ]);
  render(withSession(<UploadProgress uploadId={UID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Upload progress" });
  const source = await lastSource();
  act(() => source.open());
  act(() =>
    source.emit(
      "item.status",
      { item_id: "i1", status: "published", document_id: "d1", type_check: "match" },
      "9",
    ),
  );
  const first = screen.getAllByRole("listitem")[0];
  expect(within(first).getByText("Published")).toBeInTheDocument();
  expect(within(first).getByRole("link", { name: "Open document" })).toHaveAttribute(
    "href",
    "/documents/d1",
  );
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(f.find("POST", "/api/v1/upload-items/i3/retry")).toBeDefined();
  expect(await within(screen.getAllByRole("listitem")[2]).findByText("Queued")).toBeInTheDocument();
});

it("shows not found for an upload the user may not see", async () => {
  mockFetch([
    { path: `/api/v1/uploads/${UID}`, status: 404, body: { detail: "Upload not found." } },
  ]);
  render(withSession(<UploadProgress uploadId={UID} />, memberMe).element);
  expect(await screen.findByRole("alert")).toHaveTextContent("Upload not found.");
});
