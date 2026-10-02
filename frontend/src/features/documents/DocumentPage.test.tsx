import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { customerMe, memberMe, withSession } from "@/test/session";
import { DocumentPage } from "./DocumentPage";

const DID = "33333333-3333-3333-3333-333333333333";
const PID = "11111111-1111-1111-1111-111111111111";
const fixture = {
  id: DID,
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
  uploaded_by_name: "Owner",
  version_created_at: "2026-10-01T12:00:00+00:00",
};
const versions = [
  {
    version: 1,
    sha256: "a",
    original_path: "02-requirements/srs--portal-srs.docx",
    markdown_path: "02-requirements/srs--portal-srs.md",
    uploaded_by: "Editor",
    upload_item_id: "i1",
    created_at: "2026-10-01T10:00:00+00:00",
  },
  {
    version: 2,
    sha256: "b",
    original_path: "02-requirements/srs--portal-srs.docx",
    markdown_path: "02-requirements/srs--portal-srs.md",
    uploaded_by: "Owner",
    upload_item_id: "i2",
    created_at: "2026-10-01T12:00:00+00:00",
  },
];
const content = (version: number) => ({
  version,
  frontmatter: {
    qc_agent: 2,
    document_id: DID,
    version,
    doc_type: "srs",
    folder: "02-requirements",
    title: "Portal SRS",
    kind: "converted",
    source_file: "srs--portal-srs.docx",
    source_sha256: "b",
    uploaded_by: version === 2 ? "Owner" : "Editor",
    uploaded_at: "2026-10-01T12:00:00+00:00",
    type_selected_by_user: "srs",
    type_check: "skipped",
    language: "en",
    visibility: "internal",
    normalized_approved_by: null,
  },
  body: `## Scope v${version}\n\nThe system shall allow users to log in.\n\n<img src=x onerror="alert(1)">`,
  markdown_name: "srs--portal-srs.md",
  original_name: "srs--portal-srs.docx",
});
const project = {
  id: PID,
  slug: "demo",
  name: "Demo",
  client_name: "ACME",
  created_at: "x",
  my_role: "owner",
  settings: null,
  storage: null,
  llm_consent: null,
};

function routes(role = "owner") {
  return mockFetch([
    { path: `/api/v1/documents/${DID}`, body: fixture },
    { path: `/api/v1/documents/${DID}/versions`, body: versions },
    { path: `/api/v1/documents/${DID}/versions/2/content`, body: content(2) },
    { path: `/api/v1/documents/${DID}/versions/1/content`, body: content(1) },
    { path: `/api/v1/projects/${PID}`, body: { ...project, my_role: role } },
  ]);
}

it("renders the Markdown body through MarkdownView, the details panel and the download links", async () => {
  routes();
  render(withSession(<DocumentPage documentId={DID} />, memberMe).element);
  expect(await screen.findByRole("heading", { name: "Portal SRS" })).toBeInTheDocument();
  expect(await screen.findByRole("heading", { name: "Scope v2" })).toBeInTheDocument();
  expect(document.querySelector("img")).toBeNull(); // hostile inline HTML neutralised
  expect(screen.getByRole("link", { name: "Download original" })).toHaveAttribute(
    "href",
    `/api/v1/documents/${DID}/versions/2/original`,
  );
  expect(screen.getByRole("link", { name: "Download Markdown" })).toHaveAttribute(
    "href",
    `/api/v1/documents/${DID}/versions/2/markdown`,
  );
  await userEvent.click(screen.getByText("Details"));
  const details = screen.getByText("Details").closest("details") as HTMLElement;
  expect(within(details).getByText("Software Requirements Specification")).toBeInTheDocument();
  expect(within(details).getByText("Owner")).toBeInTheDocument();
  expect(within(details).getByText("Type check skipped")).toBeInTheDocument();
  expect(within(details).getByText("en")).toBeInTheDocument();
  expect(within(details).getByText("Internal")).toBeInTheDocument();
  expect(screen.getByText(/Rendered from the converted Markdown/)).toBeInTheDocument();
});

it("lists versions and switches the content to an older one", async () => {
  routes();
  render(withSession(<DocumentPage documentId={DID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Scope v2" });
  await userEvent.click(screen.getByRole("tab", { name: "Versions" }));
  const rows = screen.getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(within(rows[1]).getByText("Current")).toBeInTheDocument();
  expect(within(rows[0]).getByText(/Editor/)).toBeInTheDocument();
  expect(within(rows[0]).getByRole("link", { name: "Download original" })).toHaveAttribute(
    "href",
    `/api/v1/documents/${DID}/versions/1/original`,
  );
  await userEvent.click(within(rows[0]).getByRole("button", { name: "View version 1" }));
  await userEvent.click(screen.getByRole("tab", { name: "Markdown" }));
  expect(await screen.findByRole("heading", { name: "Scope v1" })).toBeInTheDocument();
  expect(screen.getByText("Showing version 1")).toBeInTheDocument();
});

it("lets an editor rename and share, but not make a shared document internal", async () => {
  const f = routes("editor");
  render(withSession(<DocumentPage documentId={DID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Portal SRS" });
  await userEvent.click(screen.getByRole("button", { name: "Edit" }));
  const dialog = screen.getByRole("dialog", { name: "Edit document" });
  await userEvent.clear(within(dialog).getByLabelText("Title"));
  await userEvent.type(within(dialog).getByLabelText("Title"), "Portal SRS v2");
  await userEvent.selectOptions(within(dialog).getByLabelText("Visibility"), "shared");
  f.fn.mockImplementationOnce(
    async () =>
      new Response(JSON.stringify({ ...fixture, title: "Portal SRS v2", visibility: "shared" }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
  );
  await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
  expect(await screen.findByRole("heading", { name: "Portal SRS v2" })).toBeInTheDocument();
  expect(screen.getByText("Shared")).toBeInTheDocument();
  // mockImplementationOnce bypassed the recorder, so read the Request from the mock's own calls
  const patch = f.fn.mock.calls
    .map(([input]) => input)
    .find((input): input is Request => input instanceof Request && input.method === "PATCH");
  expect(patch && JSON.parse(await patch.text())).toEqual({
    title: "Portal SRS v2",
    visibility: "shared",
  });
  await userEvent.click(screen.getByRole("button", { name: "Edit" }));
  const again = screen.getByRole("dialog", { name: "Edit document" });
  expect(within(again).getByRole("option", { name: "Internal" })).toBeDisabled();
  expect(
    within(again).getByText("Only a project owner can make a shared document internal."),
  ).toBeInTheDocument();
});

it("shows the not-found message for a document the user may not see", async () => {
  mockFetch([
    { path: `/api/v1/documents/${DID}`, status: 404, body: { detail: "Document not found." } },
  ]);
  render(withSession(<DocumentPage documentId={DID} />, customerMe).element);
  expect(await screen.findByRole("alert")).toHaveTextContent("Document not found.");
  expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
});

it("hides Edit from viewers and the original download from placeholders", async () => {
  mockFetch([
    {
      path: `/api/v1/documents/${DID}`,
      body: {
        ...fixture,
        is_stub: true,
        current_version: 1,
        title: "Business Requirements Document",
        doc_type: "brd",
      },
    },
    { path: `/api/v1/documents/${DID}/versions`, body: [{ ...versions[0], original_path: null }] },
    {
      path: `/api/v1/documents/${DID}/versions/1/content`,
      body: {
        ...content(1),
        original_name: null,
        frontmatter: { ...content(1).frontmatter, kind: "stub" },
      },
    },
    { path: `/api/v1/projects/${PID}`, body: { ...project, my_role: "viewer" } },
  ]);
  render(withSession(<DocumentPage documentId={DID} />, memberMe).element);
  await screen.findByRole("heading", { name: "Business Requirements Document" });
  expect(screen.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "Download original" })).not.toBeInTheDocument();
  expect(screen.getByText("Placeholders have no original file.")).toBeInTheDocument();
  expect(screen.getByText("Placeholder")).toBeInTheDocument();
});
