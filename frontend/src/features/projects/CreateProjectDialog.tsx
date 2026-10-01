"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import type { AvailableConnection, Project } from "./types";

type Props = { onClose: () => void; onCreated: (project: Project) => void };

export function CreateProjectDialog({ onClose, onCreated }: Props) {
  const [connections, setConnections] = useState<AvailableConnection[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [name, setName] = useState("");
  const [clientName, setClientName] = useState("");
  const [root, setRoot] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.GET("/api/v1/storage-connections/available").then(
      ({ data, error: apiError }) => {
        if (cancelled) return;
        if (!data) {
          setError(apiErrorMessage(apiError, m.common.loadFailed));
          return;
        }
        setConnections(data);
        setConnectionId(data.find((c) => c.is_default)?.id ?? data[0]?.id ?? "");
      },
      () => {
        if (!cancelled) setError(m.common.loadFailed);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/projects", {
        body: {
          name,
          client_name: clientName.trim() || null,
          storage_connection_id: connectionId || null,
          storage_root: root.trim() || null,
        },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onCreated(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open title={m.projects.newProject} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert kind="error">{error}</Alert> : null}
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
        <Select
          label={m.projects.storageConnection}
          required
          value={connectionId}
          onChange={(event) => setConnectionId(event.target.value)}
        >
          {connections.map((connection) => (
            <option key={connection.id} value={connection.id}>
              {connection.name} ({m.storage.typeLabels[connection.type] ?? connection.type})
            </option>
          ))}
        </Select>
        <Field
          label={m.projects.rootFolder}
          hint={m.projects.rootFolderHint}
          maxLength={80}
          pattern="[A-Za-z0-9][A-Za-z0-9._-]*"
          value={root}
          onChange={(event) => setRoot(event.target.value)}
        />
        <details className="text-sm">
          <summary className="cursor-pointer text-brand">{m.projects.consentLink}</summary>
          <p className="mt-2 text-muted">{m.projects.consentExplain}</p>
        </details>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {m.common.cancel}
          </Button>
          <Button type="submit" busy={busy}>
            {m.projects.createAction}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
