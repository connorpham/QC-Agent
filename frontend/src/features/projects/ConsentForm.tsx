"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";

export function ConsentForm({
  projectId,
  onRecorded,
}: {
  projectId: string;
  onRecorded: () => void;
}) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST(
        "/api/v1/projects/{project_id}/llm-consent",
        {
          params: { path: { project_id: projectId } },
          body: { confirmed_by_name: name },
        },
      );
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onRecorded();
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="flex max-w-lg items-end gap-2">
      {error ? <Alert kind="error">{error}</Alert> : null}
      <div className="grow">
        <Field
          label={m.projects.confirmedByName}
          required
          maxLength={200}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <Button type="submit" busy={busy}>
        {m.projects.recordConsent}
      </Button>
    </form>
  );
}
