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
import { CreateUserDialog } from "./CreateUserDialog";
import { TemporaryPasswordDialog } from "./TemporaryPasswordDialog";
import type { User } from "./types";

type Shown = { email: string; password: string } | null;

export function UsersAdmin() {
  const users = useLoad(() => api.GET("/api/v1/users").then((r) => unwrap(r)), []);
  const [creating, setCreating] = useState(false);
  const [shown, setShown] = useState<Shown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(
    action: () => Promise<{ error?: unknown; response: Response }>,
    done?: string,
  ) {
    setError(null);
    setNotice(null);
    try {
      const { error: apiError, response } = await action();
      if (!response.ok) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      if (done) setNotice(done);
      users.reload();
    } catch {
      setError(m.common.requestFailed);
    }
  }

  function setActive(user: User, active: boolean) {
    if (!active && !window.confirm(m.users.confirmDeactivate)) return;
    void run(() =>
      api.PATCH("/api/v1/users/{user_id}", {
        params: { path: { user_id: user.id } },
        body: { is_active: active },
      }),
    );
  }

  async function resetPassword(user: User) {
    if (!window.confirm(m.users.confirmResetPassword)) return;
    setError(null);
    const { data, error: apiError } = await api.POST("/api/v1/users/{user_id}/reset-password", {
      params: { path: { user_id: user.id } },
    });
    if (!data) {
      setError(apiErrorMessage(apiError, m.common.requestFailed));
      return;
    }
    setShown({ email: user.email, password: data.temporary_password });
    users.reload();
  }

  function resetMfa(user: User) {
    if (!window.confirm(m.users.confirmResetMfa)) return;
    void run(
      () =>
        api.POST("/api/v1/users/{user_id}/reset-mfa", { params: { path: { user_id: user.id } } }),
      m.users.mfaReset,
    );
  }

  return (
    <>
      <PageHeader
        title={m.users.title}
        actions={<Button onClick={() => setCreating(true)}>{m.users.newUser}</Button>}
      />
      {error ? <Alert kind="error">{error}</Alert> : null}
      {notice ? <Alert kind="success">{notice}</Alert> : null}
      {users.error ? <Alert kind="error">{users.error}</Alert> : null}
      {users.loading ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : null}
      {users.data ? (
        <Table caption={m.users.title}>
          <thead>
            <tr>
              <Th>{m.users.email}</Th>
              <Th>{m.users.displayName}</Th>
              <Th>{m.users.accountType}</Th>
              <Th>{m.users.status}</Th>
              <Th>{m.users.mfa}</Th>
              <Th>{m.common.actions}</Th>
            </tr>
          </thead>
          <tbody>
            {users.data.map((user) => (
              <tr key={user.id}>
                <Td>{user.email}</Td>
                <Td>{user.display_name}</Td>
                <Td>
                  {user.account_type === "customer" ? m.users.customer : m.users.internal}
                  {user.is_admin ? (
                    <>
                      {" "}
                      <Badge tone="warning">{m.users.isAdmin}</Badge>
                    </>
                  ) : null}
                </Td>
                <Td>
                  <span className="flex flex-wrap gap-1">
                    <Badge tone={user.is_active ? "success" : "danger"}>
                      {user.is_active ? m.users.active : m.users.inactive}
                    </Badge>
                    {user.locked_until && new Date(user.locked_until) > new Date() ? (
                      <Badge tone="danger">{m.users.locked}</Badge>
                    ) : null}
                    {user.must_change_password ? <Badge>{m.users.mustChange}</Badge> : null}
                  </span>
                </Td>
                <Td>{user.mfa_enabled ? m.users.enrolled : m.users.notEnrolled}</Td>
                <Td>
                  <span className="flex flex-wrap gap-1">
                    <Button
                      variant={user.is_active ? "danger" : "secondary"}
                      onClick={() => setActive(user, !user.is_active)}
                    >
                      {user.is_active ? m.users.deactivate : m.users.reactivate}
                    </Button>
                    <Button variant="secondary" onClick={() => void resetPassword(user)}>
                      {m.users.resetPassword}
                    </Button>
                    <Button variant="secondary" onClick={() => resetMfa(user)}>
                      {m.users.resetMfa}
                    </Button>
                  </span>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      ) : null}
      {creating ? (
        <CreateUserDialog
          onClose={() => setCreating(false)}
          onCreated={(user, password) => {
            setCreating(false);
            setShown({ email: user.email, password });
            users.reload();
          }}
        />
      ) : null}
      {shown ? (
        <TemporaryPasswordDialog
          email={shown.email}
          password={shown.password}
          onClose={() => setShown(null)}
        />
      ) : null}
    </>
  );
}
