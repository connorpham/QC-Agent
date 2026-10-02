"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { MarkdownView } from "@/components/ui/Markdown";
import { PageHeader } from "@/components/ui/PageHeader";
import { Tabs } from "@/components/ui/Tabs";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";
import { EditDocumentDialog } from "./EditDocumentDialog";
import { FrontmatterPanel } from "./FrontmatterPanel";
import { canEdit, markdownUrl, originalUrl, type Document } from "./types";

const TYPE_TITLES: Record<string, string> = {
  readme: "Project README",
  "project-charter": "Project Charter",
  glossary: "Glossary",
  brd: "Business Requirements Document",
  srs: "Software Requirements Specification",
  "use-cases": "Use Cases",
  "user-stories": "User Stories",
  "architecture-c4": "Architecture (C4)",
  erd: "Entity Relationship Diagram",
  workflows: "Workflows",
  "api-spec": "API Specification",
  "repo-structure": "Repository Structure",
  "coding-conventions": "Coding Conventions",
  adr: "Architecture Decision Record",
  "test-plan": "Test Plan",
  "test-cases": "Test Cases",
  "test-report": "Test Report",
  "deploy-guide": "Deployment Guide",
  runbook: "Runbook",
  "release-notes": "Release Notes",
};

function typeTitle(key: string): string {
  return TYPE_TITLES[key] ?? (key.endsWith("/other") ? "Other" : key);
}

export function DocumentPage({ documentId }: { documentId: string }) {
  const [override, setOverride] = useState<Document | null>(null);
  const [editing, setEditing] = useState(false);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [tab, setTab] = useState("markdown");
  // Fetched together so the document and the viewer's role in its project arrive in the same
  // render: loading them through separate hooks let the "Portal SRS" heading appear before the
  // project request (which only starts once the document reveals its project_id) had resolved,
  // so Edit briefly rendered as absent even for an editor.
  const loaded = useLoad(async () => {
    const doc = await api
      .GET("/api/v1/documents/{document_id}", { params: { path: { document_id: documentId } } })
      .then((r) => unwrap(r, m.documents.notFound));
    const project = await api
      .GET("/api/v1/projects/{project_id}", { params: { path: { project_id: doc.project_id } } })
      .then((r) => unwrap(r, m.projects.notFound));
    return { doc, role: project.my_role };
  }, [documentId]);
  const doc = override ?? loaded.data?.doc;
  const role = loaded.data?.role ?? "";
  const versions = useLoad(
    () =>
      doc
        ? api
            .GET("/api/v1/documents/{document_id}/versions", {
              params: { path: { document_id: documentId } },
            })
            .then((r) => unwrap(r))
        : Promise.resolve(null),
    [documentId, doc?.current_version],
  );
  const version = selectedVersion ?? doc?.current_version ?? null;
  const content = useLoad(
    () =>
      doc && version !== null
        ? api
            .GET("/api/v1/documents/{document_id}/versions/{version}/content", {
              params: { path: { document_id: documentId, version } },
            })
            .then((r) => unwrap(r))
        : Promise.resolve(null),
    [documentId, version, doc !== undefined],
  );

  if (loaded.error) return <Alert kind="error">{loaded.error}</Alert>;
  if (!doc) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  const editable = canEdit(role) && !doc.is_stub;
  const isCurrent = version === doc.current_version;
  const original = content.data?.original_name;

  return (
    <>
      <PageHeader
        title={doc.title}
        actions={
          <>
            <Link
              href={`/projects/${doc.project_id}`}
              className="inline-flex min-h-10 items-center text-sm text-brand underline"
            >
              {m.uploads.backToProject}
            </Link>
            {editable ? (
              <Button variant="secondary" onClick={() => setEditing(true)}>
                {m.common.edit}
              </Button>
            ) : null}
          </>
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Badge>{typeTitle(doc.doc_type)}</Badge>
        {doc.is_stub ? (
          <Badge tone="warning">{m.documents.stub}</Badge>
        ) : (
          <Badge>{m.documents.version(doc.current_version)}</Badge>
        )}
        <Badge tone={doc.visibility === "shared" ? "success" : "neutral"}>
          {doc.visibility === "shared" ? m.documents.shared : m.documents.internal}
        </Badge>
        {version !== null && !isCurrent ? (
          <Badge tone="warning">{m.documents.showing(version)}</Badge>
        ) : null}
      </div>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          <Tabs
            label={doc.title}
            value={tab}
            onChange={setTab}
            items={[
              {
                id: "markdown",
                label: m.documents.tabMarkdown,
                render: () =>
                  content.error ? (
                    <Alert kind="error">{content.error}</Alert>
                  ) : !content.data ? (
                    <p role="status" className="text-muted">
                      {m.app.loading}
                    </p>
                  ) : (
                    <>
                      <p className="mb-3 text-xs text-muted">{m.documents.renderedNote}</p>
                      <MarkdownView markdown={content.data.body} />
                    </>
                  ),
              },
              {
                id: "versions",
                label: m.documents.tabVersions,
                render: () =>
                  versions.error ? (
                    <Alert kind="error">{versions.error}</Alert>
                  ) : !versions.data ? (
                    <p role="status" className="text-muted">
                      {m.app.loading}
                    </p>
                  ) : (
                    <ul className="space-y-2">
                      {versions.data.map((v) => (
                        <li
                          key={v.version}
                          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface p-3 text-sm"
                        >
                          <div>
                            <p className="font-medium">
                              {m.documents.versionLabel(v.version)}{" "}
                              {v.version === doc.current_version ? (
                                <Badge tone="success">{m.documents.current}</Badge>
                              ) : null}
                            </p>
                            <p className="text-xs text-muted">
                              {v.uploaded_by} · {formatDateTime(v.created_at)}
                            </p>
                          </div>
                          <div className="flex flex-wrap gap-3">
                            {v.version !== version ? (
                              <Button
                                variant="secondary"
                                onClick={() => setSelectedVersion(v.version)}
                              >
                                {m.documents.viewVersion(v.version)}
                              </Button>
                            ) : null}
                            {v.original_path ? (
                              <a
                                href={originalUrl(documentId, v.version)}
                                download
                                className="inline-flex min-h-10 items-center text-brand underline"
                              >
                                {m.documents.downloadOriginal}
                              </a>
                            ) : null}
                            <a
                              href={markdownUrl(documentId, v.version)}
                              download
                              className="inline-flex min-h-10 items-center text-brand underline"
                            >
                              {m.documents.downloadMarkdown}
                            </a>
                          </div>
                        </li>
                      ))}
                    </ul>
                  ),
              },
            ]}
          />
        </div>
        <aside className="space-y-3">
          <div className="flex flex-col gap-2 text-sm">
            {version !== null && original ? (
              <a
                href={originalUrl(documentId, version)}
                download
                className="inline-flex min-h-10 items-center text-brand underline"
              >
                {m.documents.downloadOriginal}
              </a>
            ) : null}
            {doc.is_stub ? <p className="text-muted">{m.documents.noOriginal}</p> : null}
            {version !== null ? (
              <a
                href={markdownUrl(documentId, version)}
                download
                className="inline-flex min-h-10 items-center text-brand underline"
              >
                {m.documents.downloadMarkdown}
              </a>
            ) : null}
          </div>
          {content.data ? (
            <FrontmatterPanel
              frontmatter={content.data.frontmatter}
              typeTitle={typeTitle(doc.doc_type)}
            />
          ) : null}
        </aside>
      </div>
      {editing ? (
        <EditDocumentDialog
          doc={doc}
          role={role}
          onClose={() => setEditing(false)}
          onSaved={(saved) => {
            setOverride(saved);
            setEditing(false);
          }}
        />
      ) : null}
    </>
  );
}
