import type { Upload } from "./types";

/** Payload of an `item.status` Server-Sent Event (backend `app/services/events.py`). */
export type ItemStatusEvent = {
  item_id: string;
  status: string;
  type_check?: string | null;
  check_explanation?: string | null;
  suggested_doc_type?: string | null;
  final_doc_type?: string | null;
  error?: string | null;
  document_id?: string | null;
  version?: number | null;
};

export function parseItemEvent(data: string): ItemStatusEvent | null {
  try {
    const parsed = JSON.parse(data) as Partial<ItemStatusEvent>;
    if (typeof parsed.item_id !== "string" || typeof parsed.status !== "string") return null;
    return parsed as ItemStatusEvent;
  } catch {
    return null;
  }
}

/** Payload of the `upload.settled` frame: besides `upload_id`/`last_event_id`, it carries the
 * final state of every item (controller ruling P5-4 — event ids are allocated before commit,
 * so a late-committing lower id could otherwise be skipped forever). */
export type UploadSettledEvent = {
  upload_id: string;
  last_event_id?: number | null;
  items?: ItemStatusEvent[];
};

export function parseSettledEvent(data: string): UploadSettledEvent | null {
  try {
    const parsed = JSON.parse(data) as Partial<UploadSettledEvent>;
    if (typeof parsed.upload_id !== "string") return null;
    return parsed as UploadSettledEvent;
  } catch {
    return null;
  }
}

/** New upload state with the event applied to its item; the same object when no item matches. */
export function applyItemEvent(upload: Upload, event: ItemStatusEvent): Upload {
  const index = upload.items.findIndex((item) => item.id === event.item_id);
  if (index === -1) return upload;
  const item = upload.items[index];
  const next = {
    ...item,
    status: event.status,
    type_check: event.type_check === undefined ? item.type_check : event.type_check,
    check_explanation:
      event.check_explanation === undefined ? item.check_explanation : event.check_explanation,
    suggested_doc_type:
      event.suggested_doc_type === undefined ? item.suggested_doc_type : event.suggested_doc_type,
    final_doc_type: event.final_doc_type === undefined ? item.final_doc_type : event.final_doc_type,
    error: event.error === undefined ? item.error : event.error,
    document_id: event.document_id === undefined ? item.document_id : event.document_id,
  };
  const items = upload.items.slice();
  items[index] = next;
  return { ...upload, items };
}
