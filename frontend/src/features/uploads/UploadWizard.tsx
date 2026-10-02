"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Select } from "@/components/ui/Select";
import { TypeOptions } from "@/components/ui/TypeOptions";
import { api } from "@/lib/api/client";
import { unwrap } from "@/lib/api/errors";
import { uploadMultipart, type UploadOut } from "@/lib/api/upload";
import { useLoad } from "@/lib/hooks/useLoad";
import { cx } from "@/lib/cx";
import { m } from "@/messages";
import { FileRow, type RowState } from "./FileRow";
import { batchGuard, guardFile } from "./limits";
import type { Visibility } from "./types";

function titleFromFilename(name: string): string {
  const base = name.replace(/\\/g, "/").split("/").pop() ?? name;
  const dot = base.lastIndexOf(".");
  const stem = dot > 0 ? base.slice(0, dot) : base;
  return (
    stem
      .replace(/[_\-\s]+/g, " ")
      .trim()
      .slice(0, 200) || "Untitled"
  );
}

let counter = 0;

export function UploadWizard({ projectId }: { projectId: string }) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<RowState[]>([]);
  const [dragging, setDragging] = useState(false);
  const [bulkType, setBulkType] = useState("");
  const [bulkVisibility, setBulkVisibility] = useState<Visibility | "">("");
  const [formError, setFormError] = useState<string | null>(null);
  const [consentBlocked, setConsentBlocked] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<UploadOut | null>(null);

  const taxonomy = useLoad(() => api.GET("/api/v1/taxonomy").then((r) => unwrap(r)), []);
  const limits = useLoad(() => api.GET("/api/v1/upload-limits").then((r) => unwrap(r)), []);
  const project = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}", { params: { path: { project_id: projectId } } })
        .then((r) => unwrap(r, m.projects.notFound)),
    [projectId],
  );

  const uploading = progress !== null;
  useEffect(() => {
    if (!uploading) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = m.uploads.leaveWarning;
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [uploading]);

  const clientUser = project.data?.my_role === "client";
  const sendable = rows.filter((row) => row.error === null);
  const batchError = limits.data
    ? batchGuard(
        sendable.map((r) => r.file),
        limits.data,
      )
    : null;

  function addFiles(files: FileList | File[]) {
    if (!limits.data) return;
    const current = limits.data;
    const added = Array.from(files).map<RowState>((file) => ({
      key: `f${(counter += 1)}`,
      file,
      error: guardFile(file, current),
      docType: "",
      title: titleFromFilename(file.name),
      intent: "new",
      targetDocumentId: null,
      visibility: "internal",
    }));
    setRows((existing) => [...existing, ...added]);
    setFormError(null);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    addFiles(event.dataTransfer.files);
  }

  function update(key: string, next: RowState) {
    setRows((existing) => existing.map((row) => (row.key === key ? next : row)));
  }

  function applyToAll() {
    setRows((existing) =>
      existing.map((row) => ({
        ...row,
        docType: bulkType || row.docType,
        intent: bulkType && bulkType !== row.docType ? "new" : row.intent,
        targetDocumentId: bulkType && bulkType !== row.docType ? null : row.targetDocumentId,
        visibility: bulkVisibility || row.visibility,
      })),
    );
  }

  async function submit() {
    setFormError(null);
    setConsentBlocked(false);
    if (sendable.length === 0) {
      setFormError(m.uploads.nothingToUpload);
      return;
    }
    if (sendable.some((row) => !row.docType)) {
      setFormError(m.uploads.typeRequired);
      return;
    }
    const form = new FormData();
    for (const row of sendable) form.append("files", row.file, row.file.name);
    form.append(
      "items",
      JSON.stringify(
        sendable.map((row) => ({
          doc_type: row.docType,
          title: row.title.trim() || null,
          intent: row.intent,
          target_document_id: row.intent === "version" ? row.targetDocumentId : null,
          visibility: clientUser ? "shared" : row.visibility,
        })),
      ),
    );
    setProgress(0);
    try {
      const response = await uploadMultipart(
        `/api/v1/projects/${projectId}/uploads`,
        form,
        (fraction) => setProgress(Math.round(fraction * 100)),
      );
      if (!response.ok) {
        if (response.status === 409) setConsentBlocked(true);
        else {
          const detail = (response.error as { detail?: unknown } | null)?.detail;
          const message =
            detail && typeof detail === "object" && "message" in detail
              ? String((detail as { message: unknown }).message)
              : typeof detail === "string"
                ? detail
                : m.common.requestFailed;
          const rejected =
            detail && typeof detail === "object" && "rejected" in detail
              ? (detail as { rejected: { name: string; reason: string }[] }).rejected
              : [];
          setFormError([message, ...rejected.map((r) => `${r.name}: ${r.reason}`)].join(" "));
        }
        return;
      }
      if (response.data.rejected.length > 0) {
        setResult(response.data);
        return;
      }
      router.push(`/uploads/${response.data.id}`);
    } catch {
      setFormError(m.common.requestFailed);
    } finally {
      setProgress(null);
    }
  }

  const loadError = taxonomy.error ?? limits.error ?? project.error;
  if (loadError) return <Alert kind="error">{loadError}</Alert>;
  if (!taxonomy.data || !limits.data || !project.data) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  const taxonomyData = taxonomy.data;

  return (
    <>
      <PageHeader
        title={m.uploads.title}
        actions={
          <Link href={`/projects/${projectId}`} className="text-sm text-brand underline">
            {m.uploads.backToProject}
          </Link>
        }
      />
      <p className="mb-4 text-sm text-muted">{m.uploads.intro}</p>
      <div
        data-dropzone
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={cx(
          "mb-6 flex flex-col items-center gap-3 rounded-lg border-2 border-dashed p-6 text-center",
          dragging ? "border-brand bg-brand/5" : "border-border",
        )}
      >
        <p className="text-sm text-muted">{m.uploads.dropHere}</p>
        <label htmlFor="wizard-files" className="sr-only">
          {m.uploads.chooseFiles}
        </label>
        <input
          id="wizard-files"
          ref={inputRef}
          type="file"
          multiple
          className="sr-only"
          onChange={(event) => {
            if (event.target.files) addFiles(event.target.files);
            event.target.value = "";
          }}
        />
        <Button variant="secondary" onClick={() => inputRef.current?.click()}>
          {m.uploads.chooseFiles}
        </Button>
      </div>
      {rows.length === 0 ? <p className="text-muted">{m.uploads.noFiles}</p> : null}
      {rows.length > 1 ? (
        <div className="mb-4 grid gap-3 rounded-lg border border-border p-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
          <Select
            label={m.uploads.applyTypeToAll}
            value={bulkType}
            onChange={(event) => setBulkType(event.target.value)}
          >
            <option value="">—</option>
            <TypeOptions taxonomy={taxonomyData} />
          </Select>
          {clientUser ? (
            <div />
          ) : (
            <Select
              label={m.uploads.applyVisibilityToAll}
              value={bulkVisibility}
              onChange={(event) => setBulkVisibility(event.target.value as Visibility | "")}
            >
              <option value="">—</option>
              <option value="internal">{m.uploads.visibilityInternal}</option>
              <option value="shared">{m.uploads.visibilityShared}</option>
            </Select>
          )}
          <Button variant="secondary" onClick={applyToAll} disabled={!bulkType && !bulkVisibility}>
            {m.uploads.apply}
          </Button>
        </div>
      ) : null}
      <ul className="space-y-3">
        {rows.map((row) => (
          <FileRow
            key={row.key}
            row={row}
            projectId={projectId}
            taxonomy={taxonomyData}
            clientUser={clientUser}
            onChange={(next) => update(row.key, next)}
            onRemove={() => setRows((existing) => existing.filter((r) => r.key !== row.key))}
          />
        ))}
      </ul>
      <div className="mt-6 space-y-3">
        {batchError ? <Alert kind="error">{batchError}</Alert> : null}
        {formError ? <Alert kind="error">{formError}</Alert> : null}
        {consentBlocked ? (
          <Alert kind="error">
            {m.uploads.consentRequired}{" "}
            <Link href={`/projects/${projectId}`} className="underline">
              {m.uploads.consentLink}
            </Link>
          </Alert>
        ) : null}
        {result ? (
          <Alert kind="info">
            <p className="font-medium">{m.uploads.rejectedTitle}</p>
            <ul className="list-disc pl-5">
              {result.rejected.map((r) => (
                <li key={r.name}>
                  {r.name}: {r.reason}
                </li>
              ))}
            </ul>
            <Link href={`/uploads/${result.id}`} className="underline">
              {m.uploads.followProgress}
            </Link>
          </Alert>
        ) : null}
        {progress !== null ? (
          <div>
            <label htmlFor="wizard-progress" className="text-sm">
              {m.uploads.uploading(progress)}
            </label>
            <progress id="wizard-progress" className="block w-full" max={100} value={progress} />
          </div>
        ) : null}
        <Button
          onClick={() => void submit()}
          busy={uploading}
          disabled={rows.length === 0 || batchError !== null}
        >
          {m.uploads.submit}
        </Button>
      </div>
    </>
  );
}
