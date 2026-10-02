"use client";

import { useRef, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";
import { m } from "@/messages";
import { CONNECTION_SPECS, type ConnectionTypeSpec } from "./connectionTypes";
import { AVAILABLE_TYPES, CONNECTION_TYPES, type Connection, type ConnectionType } from "./types";

type Props = {
  connection?: Connection;
  onClose: () => void;
  onSaved: (connection: Connection) => void;
};

function initialValues(spec: ConnectionTypeSpec, connection: Connection | undefined) {
  const start: Record<string, string> = {};
  for (const field of spec.fields) {
    const current = connection?.config[field.name];
    start[field.name] = current === undefined ? (spec.defaults[field.name] ?? "") : String(current);
  }
  return start;
}

/** Create (no `connection`) or edit the non-secret settings and replace the secret. */
export function ConnectionDialog({ connection, onClose, onSaved }: Props) {
  const [name, setName] = useState(connection?.name ?? "");
  const [type, setType] = useState<ConnectionType>(
    (connection?.type as ConnectionType) ?? "localfs",
  );
  const spec = CONNECTION_SPECS[type];
  const [values, setValues] = useState<Record<string, string>>(() =>
    initialValues(CONNECTION_SPECS[(connection?.type as ConnectionType) ?? "localfs"], connection),
  );
  // The secret is an uncontrolled field: React never holds its typed value in state, so it is
  // never re-rendered as a `value` attribute (jsdom and some browsers reflect a controlled
  // input's live value into that attribute, which would otherwise put the secret in the DOM).
  // It is read once, directly off the element, at submit time.
  const secretRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function changeType(next: ConnectionType) {
    setType(next);
    setValues(initialValues(CONNECTION_SPECS[next], undefined));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const config = Object.fromEntries(
        spec.fields.map((field) => [field.name, values[field.name]?.trim() ?? ""]),
      );
      const secret = secretRef.current?.value.trim() ?? "";
      if (spec.secretField && !connection && !secret) {
        setError(m.storage.secretRequired(spec.secretField.label));
        setBusy(false);
        return;
      }
      const result = connection
        ? await api.PATCH("/api/v1/storage-connections/{connection_id}", {
            params: { path: { connection_id: connection.id } },
            body: { name, config, ...(secret ? { secret } : {}) },
          })
        : await api.POST("/api/v1/storage-connections", {
            // `is_default` has a server-side default (false) and is intentionally omitted here
            // so new connections never become the default by accident; the generated type
            // marks it required only because the schema declares a default for it.
            body: {
              type,
              name,
              config,
              ...(secret ? { secret } : {}),
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
          onChange={(event) => changeType(event.target.value as ConnectionType)}
        >
          {CONNECTION_TYPES.map((t) => (
            <option key={t} value={t} disabled={!AVAILABLE_TYPES.includes(t)}>
              {m.storage.typeLabels[t] ?? t}
            </option>
          ))}
        </Select>
        {spec.prereq ? <Alert kind="info">{spec.prereq}</Alert> : null}
        {spec.fields.map((field) => (
          <Field
            key={field.name}
            label={field.label}
            hint={field.hint}
            required
            maxLength={field.maxLength}
            value={values[field.name] ?? ""}
            onChange={(event) =>
              setValues((current) => ({ ...current, [field.name]: event.target.value }))
            }
          />
        ))}
        {spec.secretField ? (
          <Field
            key={type}
            ref={secretRef}
            label={spec.secretField.label}
            hint={
              connection ? m.storage.secretHint : (spec.secretField.hint ?? m.storage.secretHint)
            }
            type={spec.secretField.multiline ? undefined : "password"}
            multiline={spec.secretField.multiline}
            autoComplete="off"
            maxLength={spec.secretField.maxLength}
            defaultValue=""
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
