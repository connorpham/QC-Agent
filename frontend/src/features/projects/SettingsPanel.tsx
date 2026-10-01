"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import type { Project } from "./types";

type Props = { project: Project; onUpdated: (project: Project) => void };

export function SettingsPanel({ project, onUpdated }: Props) {
  const [name, setName] = useState(project.name);
  const [clientName, setClientName] = useState(project.client_name ?? "");
  const [model, setModel] = useState(project.settings?.model ?? "");
  const [checkBudget, setCheckBudget] = useState(String(project.settings?.check_budget_usd ?? ""));
  const [normalizeBudget, setNormalizeBudget] = useState(
    String(project.settings?.normalize_budget_usd ?? ""),
  );
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const { data, error: apiError } = await api.PATCH("/api/v1/projects/{project_id}", {
        params: { path: { project_id: project.id } },
        body: {
          name,
          client_name: clientName.trim() || null,
          settings: {
            model,
            check_budget_usd: Number(checkBudget),
            normalize_budget_usd: Number(normalizeBudget),
          },
        },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      setSaved(true);
      onUpdated(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="max-w-lg space-y-4">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {saved ? <Alert kind="success">{m.projects.settingsSaved}</Alert> : null}
      <Field
        label={m.projects.name}
        required
        maxLength={200}
        value={name}
        onChange={(event) => setName(event.target.value)}
      />
      <Field
        label={m.projects.clientName}
        maxLength={200}
        value={clientName}
        onChange={(event) => setClientName(event.target.value)}
      />
      <Field
        label={m.projects.model}
        required
        maxLength={100}
        value={model}
        onChange={(event) => setModel(event.target.value)}
      />
      <Field
        label={m.projects.checkBudget}
        type="number"
        step="0.1"
        min="0.1"
        max="50"
        required
        value={checkBudget}
        onChange={(event) => setCheckBudget(event.target.value)}
      />
      <Field
        label={m.projects.normalizeBudget}
        type="number"
        step="0.1"
        min="0.1"
        max="50"
        required
        value={normalizeBudget}
        onChange={(event) => setNormalizeBudget(event.target.value)}
      />
      <Button type="submit" busy={busy}>
        {m.projects.saveSettings}
      </Button>
    </form>
  );
}
