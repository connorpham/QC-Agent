import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { DocumentBrowser } from "./DocumentBrowser";

const PID = "11111111-1111-1111-1111-111111111111";
const taxonomy = {
  version: 1,
  folders: [
    {
      id: "overview",
      dir: "01-overview",
      stage: "Why",
      doc_types: [
        {
          key: "readme",
          id: "readme",
          title: "Project README",
          required: true,
          normalize: true,
          multi: false,
        },
      ],
    },
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
      id: "deployment",
      dir: "06-deployment",
      stage: "Run",
      doc_types: [
        {
          key: "runbook",
          id: "runbook",
          title: "Runbook",
          required: true,
          normalize: true,
          multi: false,
        },
      ],
    },
  ],
};
const doc = (overrides: Record<string, unknown>) => ({
  id: "d1",
  project_id: PID,
  folder_id: "requirements",
  doc_type: "srs",
  title: "Portal SRS",
  slug: "portal-srs",
  visibility: "internal",
  current_version: 2,
  is_stub: false,
  created_by: "u1",
  created_at: "2026-10-01T10:00:00+00:00",
  updated_at: "2026-10-01T12:00:00+00:00",
  uploaded_by_name: "Editor",
  version_created_at: "2026-10-01T12:00:00+00:00",
  ...overrides,
});
const documents = [
  doc({
    id: "stub-readme",
    folder_id: "overview",
    doc_type: "readme",
    title: "Project README",
    slug: "",
    is_stub: true,
    current_version: 1,
    uploaded_by_name: "Owner",
  }),
  doc({}),
  doc({
    id: "d2",
    title: "Ops Runbook",
    doc_type: "runbook",
    folder_id: "deployment",
    visibility: "shared",
  }),
];

it("groups documents by folder, shows stubs as placeholders and links to the document page", async () => {
  mockFetch([
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: documents },
  ]);
  render(<DocumentBrowser projectId={PID} role="editor" />);
  expect(await screen.findByRole("link", { name: "Portal SRS" })).toHaveAttribute(
    "href",
    "/documents/d1",
  );
  const groups = screen.getAllByRole("list", {
    name: /^(01-overview|02-requirements|06-deployment)/,
  });
  expect(groups).toHaveLength(3);
  const overview = screen.getByRole("list", { name: /^01-overview/ });
  expect(within(overview).getByText("Placeholder")).toBeInTheDocument();
  const srs = screen.getByRole("link", { name: "Portal SRS" }).closest("li") as HTMLElement;
  expect(within(srs).getByText("v2")).toBeInTheDocument();
  expect(within(srs).getByText(/Editor/)).toBeInTheDocument();
  expect(within(srs).getByText("Internal")).toBeInTheDocument();
  expect(within(srs).getByText(/Software Requirements Specification/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Upload documents" })).toHaveAttribute(
    "href",
    `/projects/${PID}/upload`,
  );
});

it("sends filters as query parameters and debounces the text search", async () => {
  const f = mockFetch([
    { path: "/api/v1/taxonomy", body: taxonomy },
    {
      path: `/api/v1/projects/${PID}/documents`,
      handler: (request) =>
        new URL(request.url).searchParams.get("q") === "portal" ? [documents[1]] : documents,
    },
  ]);
  render(<DocumentBrowser projectId={PID} role="viewer" />);
  await screen.findByRole("link", { name: "Portal SRS" });
  await userEvent.selectOptions(screen.getByLabelText("Folder"), "requirements");
  await userEvent.selectOptions(screen.getByLabelText("Document type"), "srs");
  await userEvent.selectOptions(screen.getByLabelText("Visibility"), "shared");
  await userEvent.type(screen.getByLabelText("Search titles"), "portal");
  await waitFor(() => {
    const last = f.calls
      .filter((c) => new URL(c.url).pathname === `/api/v1/projects/${PID}/documents`)
      .at(-1);
    expect(last && Object.fromEntries(new URL(last.url).searchParams)).toEqual({
      folder: "requirements",
      doc_type: "srs",
      visibility: "shared",
      q: "portal",
    });
  });
  await waitFor(() => expect(screen.queryByText("Ops Runbook")).not.toBeInTheDocument()); // only "Portal SRS" for q=portal
  expect(screen.queryByRole("link", { name: "Upload documents" })).not.toBeInTheDocument(); // viewers cannot upload
});

it("hides the visibility filter from clients and shows an empty state", async () => {
  mockFetch([
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: `/api/v1/projects/${PID}/documents`, body: [] },
  ]);
  render(<DocumentBrowser projectId={PID} role="client" />);
  expect(await screen.findByText("No documents match these filters.")).toBeInTheDocument();
  expect(screen.queryByLabelText("Visibility")).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Upload documents" })).toBeInTheDocument(); // clients upload
});
