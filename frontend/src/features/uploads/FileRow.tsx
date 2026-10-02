"use client";

import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { TypeOptions } from "@/components/ui/TypeOptions";
import { api } from "@/lib/api/client";
import { formatBytes } from "@/lib/format";
import { useDebouncedValue } from "@/lib/hooks/useDebouncedValue";
import { m } from "@/messages";
import { extensionOf } from "./limits";
import type { Intent, Taxonomy, VersionSuggestion, Visibility } from "./types";

export type RowState = {
  key: string;
  file: File;
  error: string | null; // guard failure: the row is shown but never sent
  docType: string;
  title: string;
  intent: Intent;
  targetDocumentId: string | null;
  visibility: Visibility;
};

type Props = {
  row: RowState;
  projectId: string;
  taxonomy: Taxonomy;
  clientUser: boolean;
  onChange: (next: RowState) => void;
  onRemove: () => void;
};

const SUGGESTION_THRESHOLD = 0.8; // spec 5.4

export function FileRow({ row, projectId, taxonomy, clientUser, onChange, onRemove }: Props) {
  const [suggestions, setSuggestions] = useState<VersionSuggestion[]>([]);
  const debouncedTitle = useDebouncedValue(row.title, 300);
  const isZip = extensionOf(row.file.name) === "zip";

  useEffect(() => {
    if (row.error || !row.docType || !debouncedTitle.trim() || isZip) return;
    let cancelled = false;
    api
      .GET("/api/v1/projects/{project_id}/version-suggestions", {
        params: {
          path: { project_id: projectId },
          query: { doc_type: row.docType, title: debouncedTitle },
        },
      })
      .then(({ data }) => {
        if (cancelled || !data) return;
        setSuggestions(data);
        const best = data[0];
        if (
          best &&
          best.similarity >= SUGGESTION_THRESHOLD &&
          row.intent === "new" &&
          row.targetDocumentId === null
        ) {
          onChange({ ...row, intent: "version", targetDocumentId: best.document_id });
        }
      });
    return () => {
      cancelled = true;
    };
    // `row`/`onChange` change on every edit; the lookup keys are the type and the settled title
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, row.docType, debouncedTitle, row.error, isZip]);

  const best = suggestions[0];
  return (
    <li className="space-y-3 rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium" title={row.file.name}>
            {row.file.name}
          </p>
          <p className="text-xs text-muted">{formatBytes(row.file.size)}</p>
        </div>
        <Button
          variant="secondary"
          onClick={onRemove}
          aria-label={m.uploads.removeFile(row.file.name)}
        >
          {m.common.remove}
        </Button>
      </div>
      {row.error ? (
        <Alert kind="error">{row.error}</Alert>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label={m.uploads.titleField}
            required
            maxLength={200}
            value={row.title}
            onChange={(event) => onChange({ ...row, title: event.target.value })}
          />
          <Select
            label={m.uploads.docType}
            required
            value={row.docType}
            onChange={(event) =>
              onChange({
                ...row,
                docType: event.target.value,
                intent: "new",
                targetDocumentId: null,
              })
            }
          >
            <option value="">{m.uploads.chooseType}</option>
            <TypeOptions taxonomy={taxonomy} />
          </Select>
          <fieldset className="space-y-1 text-sm sm:col-span-2">
            <legend className="font-medium">{m.uploads.intent}</legend>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name={`intent-${row.key}`}
                checked={row.intent === "new"}
                onChange={() => onChange({ ...row, intent: "new", targetDocumentId: null })}
              />
              {m.uploads.intentNew}
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name={`intent-${row.key}`}
                disabled={isZip || suggestions.length === 0}
                checked={row.intent === "version"}
                onChange={() =>
                  onChange({
                    ...row,
                    intent: "version",
                    targetDocumentId: suggestions[0]?.document_id ?? null,
                  })
                }
              />
              {m.uploads.intentVersion}
            </label>
            {isZip ? <p className="text-xs text-muted">{m.uploads.zipNoVersion}</p> : null}
            {!isZip && row.docType && suggestions.length === 0 ? (
              <p className="text-xs text-muted">{m.uploads.noSuggestions}</p>
            ) : null}
            {best && row.intent !== "version" ? (
              <p className="text-xs text-muted">
                {m.uploads.suggestionHint(best.title, best.current_version)}
              </p>
            ) : null}
            {row.intent === "version" ? (
              <Select
                label={m.uploads.versionTarget}
                value={row.targetDocumentId ?? ""}
                onChange={(event) =>
                  onChange({ ...row, targetDocumentId: event.target.value || null })
                }
              >
                {suggestions.map((s) => (
                  <option key={s.document_id} value={s.document_id}>
                    {s.title} (v{s.current_version})
                  </option>
                ))}
              </Select>
            ) : null}
            {best && row.intent === "version" ? (
              <p className="text-xs text-muted">
                {m.uploads.suggestionHint(best.title, best.current_version)}
              </p>
            ) : null}
          </fieldset>
          {clientUser ? (
            <p className="text-sm sm:col-span-2">
              <Badge>{m.uploads.sharedForced}</Badge>
            </p>
          ) : (
            <Select
              label={m.uploads.visibility}
              value={row.visibility}
              onChange={(event) =>
                onChange({ ...row, visibility: event.target.value as Visibility })
              }
            >
              <option value="internal">{m.uploads.visibilityInternal}</option>
              <option value="shared">{m.uploads.visibilityShared}</option>
            </Select>
          )}
        </div>
      )}
    </li>
  );
}
