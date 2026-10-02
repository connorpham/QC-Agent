"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { TypeOptions } from "@/components/ui/TypeOptions";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { m } from "@/messages";

export type Task = components["schemas"]["TaskOut"];
type Taxonomy = components["schemas"]["TaxonomyOut"];

type Props = {
  task: Task;
  taxonomy: Taxonomy;
  onClose: () => void;
  onConfirmed: (item: Task["item"]) => void;
  /** Called on a 409 conflict (the item is no longer waiting): the dialog stays open with its
   * conflict message, but the stale task list behind it is refreshed so the row disappears or
   * updates once the user closes the dialog. */
  onConflict?: () => void;
};

export function typeTitle(taxonomy: Taxonomy, key: string | null | undefined): string {
  if (!key) return m.common.none;
  for (const folder of taxonomy.folders) {
    const found = folder.doc_types.find((t) => t.key === key);
    if (found) return found.title;
  }
  return key;
}

/** Spec screen 6: the selected type, the check's explanation and suggestion, keep or change.
 * Without a verdict (SkipAnalyzer, or a check that failed) the dialog says so and still lets
 * the user confirm or change the type. */
export function ConfirmTypeDialog({ task, taxonomy, onClose, onConfirmed, onConflict }: Props) {
  const { item } = task;
  const [docType, setDocType] = useState(item.suggested_doc_type ?? item.selected_doc_type);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function confirm(key: string) {
    setBusy(true);
    setError(null);
    try {
      const {
        data,
        error: apiError,
        response,
      } = await api.POST("/api/v1/upload-items/{item_id}/confirm-type", {
        params: { path: { item_id: item.id } },
        body: { doc_type: key },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        // The item changed under us (another reviewer, a retry, ...): keep the conflict
        // message on screen, but refresh the list behind the dialog so the stale row is not
        // left offering a review that will only 409 again.
        if (response.status === 409) onConflict?.();
        return;
      }
      onConfirmed(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      title={m.tasks.confirmTitle}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {m.common.cancel}
          </Button>
          <Button
            variant="secondary"
            busy={busy}
            onClick={() => void confirm(item.selected_doc_type)}
          >
            {m.tasks.keep}
          </Button>
          <Button
            busy={busy}
            disabled={docType === item.selected_doc_type}
            onClick={() => void confirm(docType)}
          >
            {m.tasks.change}
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        {error ? <Alert kind="error">{error}</Alert> : null}
        <p className="font-medium">
          {item.original_name} · {task.project_name}
        </p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2">
          <dt className="text-muted">{m.tasks.selectedType}</dt>
          <dd>{typeTitle(taxonomy, item.selected_doc_type)}</dd>
          <dt className="text-muted">{m.tasks.verdict}</dt>
          <dd>{item.check_explanation ?? m.tasks.noVerdict}</dd>
          {item.suggested_doc_type ? (
            <>
              <dt className="text-muted">{m.tasks.suggested}</dt>
              <dd className="flex flex-wrap items-center gap-2">
                <span>{typeTitle(taxonomy, item.suggested_doc_type)}</span>
                <Button
                  variant="secondary"
                  onClick={() => setDocType(item.suggested_doc_type ?? item.selected_doc_type)}
                >
                  {m.tasks.useSuggested}
                </Button>
              </dd>
            </>
          ) : null}
        </dl>
        <Select
          label={m.tasks.chooseType}
          value={docType}
          onChange={(event) => setDocType(event.target.value)}
        >
          <TypeOptions taxonomy={taxonomy} />
        </Select>
      </div>
    </Dialog>
  );
}
