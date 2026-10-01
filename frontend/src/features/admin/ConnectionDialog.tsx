"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { m } from "@/messages";
import { AVAILABLE_TYPES, CONNECTION_TYPES, type Connection, type ConnectionType } from "./types";

type Props = {
  connection?: Connection;
  onClose: () => void;
  onSaved: (connection: Connection) => void;
};

/** Create (no `connection`) or edit the non-secret settings and replace the secret. */
export function ConnectionDialog({ connection, onClose, onSaved }: Props) {
  const [name, setName] = useState(connection?.name ?? "");
  const [type, setType] = useState<ConnectionType>(
    (connection?.type as ConnectionType) ?? "localfs",
  );
  const [rootPath, setRootPath] = useState(String(connection?.config.root_path ?? "."));
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hasSecret = type !== "localfs";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const config = { root_path: rootPath.trim() };
      const result = connection
        ? await api.PATCH("/api/v1/storage-connections/{connection_id}", {
            params: { path: { connection_id: connection.id } },
            body: { name, config, ...(hasSecret && secret ? { secret } : {}) },
          })
        : await api.POST("/api/v1/storage-connections", {
            // `is_default` has a server-side default (false) and is intentionally omitted here
            // so new connections never become the default by accident; the generated type
            // marks it required only because the schema declares a default for it.
            body: {
              type,
              name,
              config,
              ...(hasSecret && secret ? { secret } : {}),
            } as unknown as components["schemas"]["StorageConnectionCreate"],
          });
      if (!result.data) {
        setError(apiErrorMessage(result.error, m.common.requestFailed));
        return;
      }
      onSaved(result.data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open title={connection ? m.storage.editTitle : m.storage.createTitle} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert kind="error">{error}</Alert> : null}
        <Field
          label={m.storage.name}
          required
          maxLength={100}
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
        <Select
          label={m.storage.type}
          value={type}
          disabled={connection !== undefined}
          onChange={(event) => setType(event.target.value as ConnectionType)}
        >
          {CONNECTION_TYPES.map((t) => (
            <option key={t} value={t} disabled={!AVAILABLE_TYPES.includes(t)}>
              {m.storage.typeLabels[t] ?? t}
            </option>
          ))}
        </Select>
        <Field
          label={m.storage.rootPath}
          hint={m.storage.rootPathHint}
          required
          maxLength={500}
          value={rootPath}
          onChange={(event) => setRootPath(event.target.value)}
        />
        {hasSecret ? (
          <Field
            label={m.storage.secretField}
            hint={m.storage.secretHint}
            type="password"
            autoComplete="off"
            value={secret}
            onChange={(event) => setSecret(event.target.value)}
          />
        ) : null}
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
