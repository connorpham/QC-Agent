"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks/useDebouncedValue";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";
import { isInternal, type Document, type Taxonomy } from "./types";

const UPLOADER_ROLES = ["owner", "editor", "client"];

function typeTitle(taxonomy: Taxonomy, key: string): string {
  for (const folder of taxonomy.folders) {
    const found = folder.doc_types.find((t) => t.key === key);
    if (found) return found.title;
  }
  return key;
}

export function DocumentBrowser({ projectId, role }: { projectId: string; role: string }) {
  const [folder, setFolder] = useState("");
  const [docType, setDocType] = useState("");
  const [visibility, setVisibility] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebouncedValue(search.trim(), 300);
  const taxonomy = useLoad(() => api.GET("/api/v1/taxonomy").then((r) => unwrap(r)), []);
  const documents = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}/documents", {
          params: {
            path: { project_id: projectId },
            query: {
              folder: folder || undefined,
              doc_type: docType || undefined,
              visibility: (visibility || undefined) as "internal" | "shared" | undefined,
              q: q || undefined,
            },
          },
        })
        .then((r) => unwrap(r)),
    [projectId, folder, docType, visibility, q],
  );

  if (taxonomy.error) return <Alert kind="error">{taxonomy.error}</Alert>;
  if (!taxonomy.data) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  const folders = taxonomy.data.folders;
  const typeChoices = folders
    .filter((f) => !folder || f.id === folder)
    .flatMap((f) => f.doc_types.map((t) => ({ key: t.key, title: `${t.title}` })));
  const grouped = folders
    .map((f) => ({ folder: f, items: (documents.data ?? []).filter((d) => d.folder_id === f.id) }))
    .filter((g) => g.items.length > 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid w-full gap-3 sm:grid-cols-2 md:w-auto md:grid-cols-4">
          <Select
            label={m.documents.filterFolder}
            value={folder}
            onChange={(event) => {
              setFolder(event.target.value);
              setDocType("");
            }}
          >
            <option value="">{m.documents.allFolders}</option>
            {folders.map((f) => (
              <option key={f.id} value={f.id}>
                {f.dir} ({f.stage})
              </option>
            ))}
          </Select>
          <Select
            label={m.documents.filterType}
            value={docType}
            onChange={(event) => setDocType(event.target.value)}
          >
            <option value="">{m.documents.allTypes}</option>
            {typeChoices.map((t) => (
              <option key={t.key} value={t.key}>
                {t.title}
              </option>
            ))}
          </Select>
          {isInternal(role) ? (
            <Select
              label={m.documents.filterVisibility}
              value={visibility}
              onChange={(event) => setVisibility(event.target.value)}
            >
              <option value="">{m.common.all}</option>
              <option value="internal">{m.documents.internal}</option>
              <option value="shared">{m.documents.shared}</option>
            </Select>
          ) : null}
          <Field
            label={m.documents.search}
            type="search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </div>
        {UPLOADER_ROLES.includes(role) ? (
          <Link
            href={`/projects/${projectId}/upload`}
            className="inline-flex min-h-10 items-center rounded-md bg-brand px-3 text-sm font-medium text-brand-fg"
          >
            {m.documents.upload}
          </Link>
        ) : null}
      </div>
      {documents.error ? (
        <Alert kind="error">
          {documents.error}{" "}
          <Button variant="secondary" onClick={documents.reload}>
            {m.common.retry}
          </Button>
        </Alert>
      ) : null}
      {documents.loading && !documents.data ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : null}
      {documents.data && documents.data.length === 0 ? (
        <p className="text-muted">{m.documents.empty}</p>
      ) : null}
      {grouped.map(({ folder: f, items }) => (
        <section key={f.id}>
          <h2 id={`folder-${f.id}`} className="mb-2 text-sm font-semibold text-muted">
            {f.dir} · {f.stage}
          </h2>
          <ul aria-labelledby={`folder-${f.id}`} className="space-y-2">
            {items.map((d) => (
              <DocumentCard key={d.id} document={d} taxonomy={taxonomy.data as Taxonomy} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function DocumentCard({ document, taxonomy }: { document: Document; taxonomy: Taxonomy }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface p-3">
      <div className="min-w-0">
        <p className="truncate">
          <Link href={`/documents/${document.id}`} className="font-medium text-brand">
            {document.title}
          </Link>
        </p>
        <p className="text-xs text-muted">
          {typeTitle(taxonomy, document.doc_type)}
          {document.uploaded_by_name ? <> · {document.uploaded_by_name}</> : null}
          {document.version_created_at ? <> · {formatDate(document.version_created_at)}</> : null}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {document.is_stub ? (
          <Badge tone="warning">{m.documents.stub}</Badge>
        ) : (
          <Badge>{m.documents.version(document.current_version)}</Badge>
        )}
        <Badge tone={document.visibility === "shared" ? "success" : "neutral"}>
          {document.visibility === "shared" ? m.documents.shared : m.documents.internal}
        </Badge>
      </div>
    </li>
  );
}
