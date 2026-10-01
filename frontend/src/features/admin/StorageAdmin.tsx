"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { PageHeader } from "@/components/ui/PageHeader";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api/client";
import { apiErrorMessage, unwrap } from "@/lib/api/errors";
import { useLoad } from "@/lib/hooks/useLoad";
import { m } from "@/messages";
import { ConnectionDialog } from "./ConnectionDialog";
import type { Connection } from "./types";

type TestState = { ok: boolean; detail: string } | "running";

export function StorageAdmin() {
  const connections = useLoad(
    () => api.GET("/api/v1/storage-connections").then((r) => unwrap(r)),
    [],
  );
  const [editing, setEditing] = useState<Connection | "new" | null>(null);
  const [tests, setTests] = useState<Record<string, TestState>>({});
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function patch(
    connection: Connection,
    body: { is_default?: boolean; is_active?: boolean },
    done: string | null,
  ) {
    setError(null);
    setNotice(null);
    try {
      const { data, error: apiError } = await api.PATCH(
        "/api/v1/storage-connections/{connection_id}",
        { params: { path: { connection_id: connection.id } }, body },
      );
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      if (done) setNotice(done);
      connections.reload();
    } catch {
      setError(m.common.requestFailed);
    }
  }

  async function test(connection: Connection) {
    setTests((t) => ({ ...t, [connection.id]: "running" }));
    try {
      const { data, error: apiError } = await api.POST(
        "/api/v1/storage-connections/{connection_id}/test",
        { params: { path: { connection_id: connection.id } } },
      );
      setTests((t) => ({
        ...t,
        [connection.id]: data ?? {
          ok: false,
          detail: apiErrorMessage(apiError, m.common.requestFailed),
        },
      }));
    } catch {
      setTests((t) => ({ ...t, [connection.id]: { ok: false, detail: m.common.requestFailed } }));
    }
  }

  return (
    <>
      <PageHeader
        title={m.storage.title}
        actions={<Button onClick={() => setEditing("new")}>{m.storage.newConnection}</Button>}
      />
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}
      {connections.error ? <Alert kind="error">{connections.error}</Alert> : null}
      {connections.loading ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : null}
      {connections.data ? (
        <Table caption={m.storage.title}>
          <thead>
            <tr>
              <Th>{m.storage.name}</Th>
              <Th>{m.storage.type}</Th>
              <Th>{m.storage.rootPath}</Th>
              <Th>{m.storage.active}</Th>
              <Th>{m.storage.secret}</Th>
              <Th>{m.common.actions}</Th>
            </tr>
          </thead>
          <tbody>
            {connections.data.map((connection) => {
              const result = tests[connection.id];
              return (
                <tr key={connection.id}>
                  <Td>{connection.name}</Td>
                  <Td>{m.storage.typeLabels[connection.type] ?? connection.type}</Td>
                  <Td className="font-mono">{String(connection.config.root_path ?? "")}</Td>
                  <Td>
                    <span className="flex flex-wrap items-center gap-1">
                      <Badge tone={connection.is_active ? "success" : "danger"}>
                        {connection.is_active ? m.storage.active : m.storage.inactive}
                      </Badge>
                      {connection.is_default ? (
                        <Badge tone="success">{m.storage.default}</Badge>
                      ) : null}
                    </span>
                  </Td>
                  <Td>{connection.has_secret ? m.storage.hasSecret : m.storage.noSecret}</Td>
                  <Td>
                    <span className="flex flex-wrap items-center gap-1">
                      <Button variant="secondary" onClick={() => setEditing(connection)}>
                        {m.storage.edit}
                      </Button>
                      {connection.is_active && !connection.is_default ? (
                        <Button
                          variant="secondary"
                          onClick={() =>
                            void patch(connection, { is_default: true }, m.storage.defaultChanged)
                          }
                        >
                          {m.storage.setDefault}
                        </Button>
                      ) : null}
                      <Button
                        variant={connection.is_active ? "danger" : "secondary"}
                        onClick={() =>
                          void patch(connection, { is_active: !connection.is_active }, null)
                        }
                      >
                        {connection.is_active ? m.storage.deactivate : m.storage.reactivate}
                      </Button>
                      <Button
                        variant="secondary"
                        busy={result === "running"}
                        onClick={() => void test(connection)}
                      >
                        {m.storage.test}
                      </Button>
                      {result && result !== "running" ? (
                        <span role="status" className={result.ok ? "text-success" : "text-danger"}>
                          {result.ok
                            ? m.storage.testOk
                            : `${m.storage.testFailed}: ${result.detail}`}
                        </span>
                      ) : null}
                    </span>
                  </Td>
                </tr>
              );
            })}
          </tbody>
        </Table>
      ) : null}
      {editing ? (
        <ConnectionDialog
          connection={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            setNotice(m.storage.saved);
            connections.reload();
          }}
        />
      ) : null}
    </>
  );
}
