"use client";

import Link from "next/link";
import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { formatBytes } from "@/lib/format";
import { m } from "@/messages";
import type { UploadItem } from "./types";
import { useUploadProgress, type Connection } from "./useUploadProgress";

const CONNECTION_LABEL: Record<Connection, string> = {
  idle: "",
  connecting: m.uploads.reconnecting,
  live: m.uploads.live,
  reconnecting: m.uploads.reconnecting,
  polling: m.uploads.polling,
  closed: m.uploads.settled,
};

function ItemCard({
  item,
  onRetry,
}: {
  item: UploadItem;
  onRetry: (item: UploadItem) => Promise<void>;
}) {
  const [retryError, setRetryError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const typeCheck = item.type_check ? m.uploads.typeCheck[item.type_check] : null;
  return (
    <li className="space-y-2 rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium" title={item.original_name}>
            {item.original_name}
          </p>
          <p className="text-xs text-muted">
            {item.title} · {formatBytes(item.size)}
          </p>
        </div>
        <StatusBadge status={item.status} />
      </div>
      {item.check_explanation ? (
        <p className="text-sm text-muted">{item.check_explanation}</p>
      ) : null}
      {typeCheck ? <p className="text-xs text-muted">{typeCheck}</p> : null}
      {item.warnings.includes("low_text") ? (
        <p className="text-xs text-warning">{m.uploads.lowText}</p>
      ) : null}
      {item.status === "failed" && item.error ? (
        <p className="text-sm text-danger">{item.error}</p>
      ) : null}
      {retryError ? <Alert kind="error">{retryError}</Alert> : null}
      <div className="flex flex-wrap gap-3 text-sm">
        {item.status === "needs_confirmation" ? (
          <Link href="/tasks" className="text-brand underline">
            {m.uploads.goToTasks}
          </Link>
        ) : null}
        {item.status === "published" && item.document_id ? (
          <Link href={`/documents/${item.document_id}`} className="text-brand underline">
            {m.uploads.openDocument}
          </Link>
        ) : null}
        {item.status === "failed" ? (
          <Button
            variant="secondary"
            busy={busy}
            onClick={() => {
              setBusy(true);
              setRetryError(null);
              onRetry(item)
                .catch((reason: unknown) =>
                  setRetryError(reason instanceof Error ? reason.message : m.common.requestFailed),
                )
                .finally(() => setBusy(false));
            }}
          >
            {m.uploads.retryItem}
          </Button>
        ) : null}
      </div>
    </li>
  );
}

export function UploadProgress({ uploadId }: { uploadId: string }) {
  const progress = useUploadProgress(uploadId);
  const upload = progress.upload;

  async function retry(item: UploadItem) {
    const { data, error } = await api.POST("/api/v1/upload-items/{item_id}/retry", {
      params: { path: { item_id: item.id } },
    });
    if (!data) throw new Error(apiErrorMessage(error, m.common.requestFailed));
    progress.reload(); // the retried item is active again: the hook reopens the stream
  }

  if (progress.error) return <Alert kind="error">{progress.error}</Alert>;
  if (!upload) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  return (
    <>
      <PageHeader
        title={m.uploads.progressTitle}
        actions={
          <Link href={`/projects/${upload.project_id}`} className="text-sm text-brand underline">
            {m.uploads.backToProject}
          </Link>
        }
      />
      <p role="status" aria-label={m.uploads.connectionLabel} className="mb-4 text-sm text-muted">
        {CONNECTION_LABEL[progress.connection]}
      </p>
      <ul className="space-y-3">
        {upload.items.map((item) => (
          <ItemCard key={item.id} item={item} onRetry={retry} />
        ))}
      </ul>
    </>
  );
}
