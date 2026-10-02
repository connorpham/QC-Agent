import { expect, it } from "vitest";
import { applyItemEvent, parseItemEvent } from "./events";
import type { Upload } from "./types";

const upload: Upload = {
  id: "u1",
  project_id: "p1",
  uploaded_by: "me",
  created_at: "2026-10-02T09:00:00+00:00",
  rejected: [],
  items: [
    {
      id: "i1",
      upload_id: "u1",
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
      status: "uploaded",
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
    },
  ],
};

it("parses a frame's JSON and ignores garbage", () => {
  expect(parseItemEvent('{"item_id":"i1","status":"converting"}')).toEqual({
    item_id: "i1",
    status: "converting",
  });
  expect(parseItemEvent("not json")).toBeNull();
  expect(parseItemEvent('{"status":"converting"}')).toBeNull(); // no item id
});

it("applies status and changed fields to the matching item only", () => {
  const next = applyItemEvent(upload, {
    item_id: "i1",
    status: "published",
    type_check: "skipped",
    check_explanation: "Type check is not available yet; the selected type was kept.",
    document_id: "d1",
  });
  expect(next.items[0].status).toBe("published");
  expect(next.items[0].document_id).toBe("d1");
  expect(next.items[0].type_check).toBe("skipped");
  expect(next.items[0].title).toBe("SRS"); // untouched
  expect(upload.items[0].status).toBe("uploaded"); // immutable input
  expect(applyItemEvent(upload, { item_id: "other", status: "failed" })).toBe(upload);
});

it("clears the error when an item is retried", () => {
  const failed = applyItemEvent(upload, { item_id: "i1", status: "failed", error: "Broken." });
  expect(failed.items[0].error).toBe("Broken.");
  const retried = applyItemEvent(failed, { item_id: "i1", status: "uploaded", error: null });
  expect(retried.items[0].error).toBeNull();
});
