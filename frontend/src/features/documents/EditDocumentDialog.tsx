"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import type { Document } from "./types";

type Props = {
  doc: Document;
  role: string;
  onClose: () => void;
  onSaved: (saved: Document) => void;
};

/** Owners change anything; editors rename and may share, never hide (spec 9, Plan 2 rules). */
export function EditDocumentDialog({ doc, role, onClose, onSaved }: Props) {
  const [title, setTitle] = useState(doc.title);
  const [visibility, setVisibility] = useState(doc.visibility);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const editorCannotHide = role === "editor" && doc.visibility === "shared";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.PATCH("/api/v1/documents/{document_id}", {
        params: { path: { document_id: doc.id } },
        body: { title, visibility: visibility as "internal" | "shared" },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onSaved(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open title={m.documents.editTitle} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert kind="error">{error}</Alert> : null}
        <Field
          label={m.documents.titleField}
          required
          maxLength={200}
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
        <Select
          label={m.documents.visibilityField}
          value={visibility}
          hint={editorCannotHide ? m.documents.editorCannotHide : undefined}
          onChange={(event) => setVisibility(event.target.value)}
        >
          <option value="internal" disabled={editorCannotHide}>
            {m.documents.internal}
          </option>
          <option value="shared">{m.documents.shared}</option>
        </Select>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {m.common.cancel}
          </Button>
          <Button type="submit" busy={busy}>
            {m.common.save}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
