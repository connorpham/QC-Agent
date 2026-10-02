import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { memberMe, withSession } from "@/test/session";
import { TasksPage } from "./TasksPage";

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
  ],
};
const task = {
  item: {
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
    check_explanation: "Reads like a test plan.",
    suggested_doc_type: null,
    version_hint_document_id: null,
    warnings: [],
    conversion_meta: {},
    error: null,
    document_id: null,
    created_at: "2026-10-02T09:00:00+00:00",
    updated_at: "2026-10-02T09:05:00+00:00",
  },
  project_id: "p1",
  project_name: "Demo",
};

it("lists waiting items, opens the dialog and refreshes after a confirmation", async () => {
  let confirmed = false;
  mockFetch([
    { path: "/api/v1/me/tasks", handler: () => (confirmed ? [] : [task]) },
    { path: "/api/v1/taxonomy", body: taxonomy },
    {
      method: "POST",
      path: "/api/v1/upload-items/i1/confirm-type",
      handler: () => {
        confirmed = true;
        return { ...task.item, status: "publishing", final_doc_type: "srs" };
      },
    },
  ]);
  render(withSession(<TasksPage />, memberMe).element);
  const card = (await screen.findByText("plan.docx")).closest("li") as HTMLElement;
  expect(within(card).getByText("Demo")).toBeInTheDocument();
  expect(within(card).getByText("Needs confirmation")).toBeInTheDocument();
  await userEvent.click(within(card).getByRole("button", { name: "Review" }));
  await userEvent.click(screen.getByRole("button", { name: "Keep selected type" }));
  expect(await screen.findByText("Nothing is waiting for you.")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Type confirmed. The document is being published.",
  );
});

it("shows the empty state", async () => {
  mockFetch([
    { path: "/api/v1/me/tasks", body: [] },
    { path: "/api/v1/taxonomy", body: taxonomy },
  ]);
  render(withSession(<TasksPage />, memberMe).element);
  expect(await screen.findByText("Nothing is waiting for you.")).toBeInTheDocument();
});
