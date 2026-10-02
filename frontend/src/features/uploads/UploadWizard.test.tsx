import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { FakeXHR } from "@/test/fake-xhr";
import { customerMe, memberMe, withSession } from "@/test/session";
import { UploadWizard } from "./UploadWizard";

const { push } = vi.hoisted(() => ({ push: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push, replace: vi.fn() }) }));

const PID = "11111111-1111-1111-1111-111111111111";
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
        {
          key: "requirements/other",
          id: "other",
          title: "Other",
          required: false,
          normalize: false,
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
const limits = {
  max_file_mb: 1,
  max_batch_mb: 2,
  allowed_extensions: ["csv", "docx", "html", "md", "pdf", "pptx", "txt", "xlsx", "zip"],
  zip_max_entries: 200,
};
const project = (role: string, consent = true) => ({
  id: PID,
  slug: "demo",
  name: "Demo",
  client_name: "ACME",
  created_at: "2026-10-01T10:00:00+00:00",
  my_role: role,
  settings: null,
  storage: null,
  llm_consent: consent
    ? { confirmed_by_name: "Rep", confirmed_at: "2026-10-01T11:00:00+00:00" }
    : null,
});

function routes(role = "editor", extra: Parameters<typeof mockFetch>[0] = []) {
  return mockFetch([
    // routes are matched in order, so an override for a path below must come first
    ...extra,
    { path: "/api/v1/taxonomy", body: taxonomy },
    { path: "/api/v1/upload-limits", body: limits },
    { path: `/api/v1/projects/${PID}`, body: project(role) },
    { path: `/api/v1/projects/${PID}/version-suggestions`, body: [] },
  ]);
}

beforeEach(() => {
  FakeXHR.install();
  push.mockReset();
});

it("adds files by drop and by picker, lets the user set type and title, and uploads", async () => {
  routes();
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  const zone = await screen.findByText("Drop files here");
  fireEvent.drop(zone.closest("[data-dropzone]") as HTMLElement, {
    dataTransfer: {
      files: [new File([new Uint8Array(1234)], "Portal SRS.docx")],
      types: ["Files"],
    },
  });
  await userEvent.upload(
    screen.getByLabelText("Choose files"),
    new File(["# Runbook"], "runbook.md"),
  );
  const rows = screen.getAllByRole("listitem");
  expect(rows).toHaveLength(2);
  expect(within(rows[0]).getByLabelText("Title")).toHaveValue("Portal SRS");
  expect(within(rows[0]).getByText("1.2 KB")).toBeInTheDocument();
  await userEvent.selectOptions(within(rows[0]).getByLabelText("Document type"), "srs");
  await userEvent.selectOptions(within(rows[1]).getByLabelText("Document type"), "runbook");
  await userEvent.selectOptions(within(rows[1]).getByLabelText("Visibility"), "shared");
  await userEvent.clear(within(rows[1]).getByLabelText("Title"));
  await userEvent.type(within(rows[1]).getByLabelText("Title"), "Ops Runbook");
  FakeXHR.respondWith = {
    status: 201,
    body: {
      id: "u1",
      project_id: PID,
      uploaded_by: "me",
      created_at: "x",
      items: [],
      rejected: [],
    },
  };
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/uploads/u1"));
  const sent = FakeXHR.instances[0];
  expect(sent.url).toBe(`/api/v1/projects/${PID}/uploads`);
  const body = sent.body as FormData;
  expect(body.getAll("files").map((f) => (f as File).name)).toEqual([
    "Portal SRS.docx",
    "runbook.md",
  ]);
  expect(JSON.parse(body.get("items") as string)).toEqual([
    {
      doc_type: "srs",
      title: "Portal SRS",
      intent: "new",
      target_document_id: null,
      visibility: "internal",
    },
    {
      doc_type: "runbook",
      title: "Ops Runbook",
      intent: "new",
      target_document_id: null,
      visibility: "shared",
    },
  ]);
});

it("refuses files over the limit and unsupported extensions before upload", async () => {
  routes();
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), [
    new File([new Uint8Array(1024 * 1024 + 1)], "huge.pdf"),
    new File(["x"], "virus.exe"),
    new File(["ok"], "fine.md"),
  ]);
  const rows = screen.getAllByRole("listitem");
  expect(within(rows[0]).getByRole("alert")).toHaveTextContent("File is larger than 1 MB.");
  expect(within(rows[1]).getByRole("alert")).toHaveTextContent("File type is not supported.");
  expect(within(rows[0]).queryByLabelText("Document type")).not.toBeInTheDocument();
  await userEvent.selectOptions(within(rows[2]).getByLabelText("Document type"), "srs");
  FakeXHR.respondWith = {
    status: 201,
    body: {
      id: "u2",
      project_id: PID,
      uploaded_by: "me",
      created_at: "x",
      items: [],
      rejected: [],
    },
  };
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() => expect(FakeXHR.instances).toHaveLength(1));
  expect(
    (FakeXHR.instances[0].body as FormData).getAll("files").map((f) => (f as File).name),
  ).toEqual(["fine.md"]);
});

it("blocks a batch over the total limit and requires a type for every file", async () => {
  routes();
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), [
    new File([new Uint8Array(1024 * 1024)], "a.pdf"),
    new File([new Uint8Array(1024 * 1024)], "b.pdf"),
    new File([new Uint8Array(10)], "c.pdf"),
  ]);
  expect(screen.getByRole("alert")).toHaveTextContent("exceed 2 MB in total");
  expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Remove c.pdf" }));
  await userEvent.click(screen.getByRole("button", { name: "Remove b.pdf" }));
  expect(screen.getByRole("button", { name: "Upload" })).toBeEnabled();
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Choose a document type for every file.");
  expect(FakeXHR.instances).toHaveLength(0);
});

it("applies a type and visibility to all files and preselects a version suggestion", async () => {
  routes("owner", [
    {
      path: `/api/v1/projects/${PID}/version-suggestions`,
      handler: (request) =>
        new URL(request.url).searchParams.get("doc_type") === "srs"
          ? [{ document_id: "d-old", title: "Portal SRS", current_version: 2, similarity: 0.92 }]
          : [],
    },
  ]);
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), [
    new File(["a"], "Portal SRS v3.docx"),
    new File(["b"], "notes.md"),
  ]);
  await userEvent.selectOptions(screen.getByLabelText("Document type for all files"), "srs");
  await userEvent.selectOptions(screen.getByLabelText("Visibility for all files"), "shared");
  await userEvent.click(screen.getByRole("button", { name: "Apply" }));
  const rows = screen.getAllByRole("listitem");
  expect(within(rows[1]).getByLabelText("Document type")).toHaveValue("srs");
  expect(within(rows[1]).getByLabelText("Visibility")).toHaveValue("shared");
  expect(
    await within(rows[0]).findByText(/Looks like a new version of "Portal SRS" \(currently v2\)/),
  ).toBeInTheDocument();
  expect(within(rows[0]).getByLabelText("New version of an existing document")).toBeChecked();
  expect(within(rows[0]).getByLabelText("Existing document")).toHaveValue("d-old");
  await userEvent.click(within(rows[0]).getByLabelText("New document"));
  expect(within(rows[0]).queryByLabelText("Existing document")).not.toBeInTheDocument();
});

it("forces shared visibility for customer users and explains the consent gate", async () => {
  routes("client");
  render(withSession(<UploadWizard projectId={PID} />, customerMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), new File(["a"], "brd.docx"));
  const row = screen.getByRole("listitem");
  expect(within(row).queryByLabelText("Visibility")).not.toBeInTheDocument();
  expect(
    within(row).getByText(/Shared \(documents uploaded by customer users are always shared\)/),
  ).toBeInTheDocument();
  await userEvent.selectOptions(within(row).getByLabelText("Document type"), "srs");
  FakeXHR.respondWith = {
    status: 409,
    body: {
      detail:
        "The project owner must confirm LLM data processing before documents can be uploaded.",
    },
  };
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(
    "has not recorded the customer's LLM data-processing confirmation",
  );
  expect(
    within(alert).getByRole("link", { name: "Record it on the project's Overview tab" }),
  ).toHaveAttribute("href", `/projects/${PID}`);
  expect(
    JSON.parse((FakeXHR.instances[0].body as FormData).get("items") as string)[0].visibility,
  ).toBe("shared");
});

it("shows rejected files and offers to follow the progress", async () => {
  routes();
  render(withSession(<UploadWizard projectId={PID} />, memberMe).element);
  await screen.findByText("Drop files here");
  await userEvent.upload(screen.getByLabelText("Choose files"), new File(["a"], "a.docx"));
  await userEvent.selectOptions(screen.getByLabelText("Document type"), "srs");
  FakeXHR.respondWith = {
    status: 201,
    body: {
      id: "u3",
      project_id: PID,
      uploaded_by: "me",
      created_at: "x",
      items: [],
      rejected: [{ name: "a.docx", reason: "Zip archives cannot be uploaded as a new version." }],
    },
  };
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
  expect(await screen.findByText("Some files were not accepted")).toBeInTheDocument();
  expect(screen.getByText(/Zip archives cannot be uploaded/)).toBeInTheDocument();
  expect(push).not.toHaveBeenCalled();
  expect(screen.getByRole("link", { name: "Follow progress" })).toHaveAttribute(
    "href",
    "/uploads/u3",
  );
});
