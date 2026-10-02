import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { ConfirmTypeDialog } from "./ConfirmTypeDialog";

const taxonomy = {
  version: 1,
  folders: [
    {
      id: "requirements",
      dir: "02-requirements",
      stage: "What",
      doc_types: [
        {
          key: "srs",
          id: "srs",
          title: "Software Requirements Specification",
          required: true,
          normalize: true,
          multi: false,
        },
      ],
    },
    {
      id: "testing",
      dir: "05-testing",
      stage: "Verify",
      doc_types: [
        {
          key: "test-plan",
          id: "test-plan",
          title: "Test Plan",
          required: true,
          normalize: true,
          multi: false,
        },
      ],
    },
  ],
};
const item = (overrides: Record<string, unknown> = {}) => ({
  id: "i1",
  upload_id: "u1",
  original_name: "plan.docx",
  ext: "docx",
  size: 10,
  sha256: "x",
  selected_doc_type: "srs",
  final_doc_type: null,
  title: "Plan",
  intent: "new",
  target_document_id: null,
  visibility: "internal",
  status: "needs_confirmation",
  type_check: null,
  check_explanation: "Reads like a test plan: scope, entry criteria, schedule.",
  suggested_doc_type: "test-plan",
  version_hint_document_id: null,
  warnings: [],
  conversion_meta: {},
  error: null,
  document_id: null,
  created_at: "2026-10-02T09:00:00+00:00",
  updated_at: "2026-10-02T09:05:00+00:00",
  ...overrides,
});
const task = (overrides: Record<string, unknown> = {}) => ({
  item: item(overrides),
  project_id: "p1",
  project_name: "Demo",
});

it("shows the selected type, the explanation and the suggestion, and changes the type", async () => {
  const f = mockFetch([
    {
      method: "POST",
      path: "/api/v1/upload-items/i1/confirm-type",
      body: item({ status: "publishing", final_doc_type: "test-plan" }),
    },
  ]);
  const onConfirmed = vi.fn();
  render(
    <ConfirmTypeDialog
      task={task()}
      taxonomy={taxonomy}
      onClose={vi.fn()}
      onConfirmed={onConfirmed}
    />,
  );
  const dialog = screen.getByRole("dialog", { name: "Confirm the document type" });
  // each title appears twice: as the "You selected" / "Suggested type" value and as a <select> option
  expect(within(dialog).getAllByText("Software Requirements Specification")).toHaveLength(2);
  expect(
    within(dialog).getByText("Reads like a test plan: scope, entry criteria, schedule."),
  ).toBeInTheDocument();
  expect(within(dialog).getAllByText("Test Plan")).toHaveLength(2);
  expect(within(dialog).getByLabelText("Document type to publish with")).toHaveValue("test-plan"); // suggestion preselected
  await userEvent.click(within(dialog).getByRole("button", { name: "Change type" }));
  expect(await f.body(0)).toEqual({ doc_type: "test-plan" });
  expect(onConfirmed).toHaveBeenCalledTimes(1);
});

it("keeps the selected type with one click", async () => {
  const f = mockFetch([
    {
      method: "POST",
      path: "/api/v1/upload-items/i1/confirm-type",
      body: item({ status: "publishing", final_doc_type: "srs" }),
    },
  ]);
  render(
    <ConfirmTypeDialog task={task()} taxonomy={taxonomy} onClose={vi.fn()} onConfirmed={vi.fn()} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Keep selected type" }));
  expect(await f.body(0)).toEqual({ doc_type: "srs" });
});

it("handles an item without a verdict", () => {
  mockFetch([]);
  render(
    <ConfirmTypeDialog
      task={task({ check_explanation: null, suggested_doc_type: null })}
      taxonomy={taxonomy}
      onClose={vi.fn()}
      onConfirmed={vi.fn()}
    />,
  );
  expect(screen.getByText(/did not return a verdict/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Use the suggested type" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Document type to publish with")).toHaveValue("srs");
});

it("shows the conflict message when the item is no longer waiting", async () => {
  mockFetch([
    {
      method: "POST",
      path: "/api/v1/upload-items/i1/confirm-type",
      status: 409,
      body: { detail: "This item is not waiting for a type confirmation." },
    },
  ]);
  const onConfirmed = vi.fn();
  render(
    <ConfirmTypeDialog
      task={task()}
      taxonomy={taxonomy}
      onClose={vi.fn()}
      onConfirmed={onConfirmed}
    />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Keep selected type" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This item is not waiting for a type confirmation.",
  );
  expect(onConfirmed).not.toHaveBeenCalled();
});
