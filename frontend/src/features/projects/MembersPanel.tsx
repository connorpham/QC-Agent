"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { Table, Td, Th } from "@/components/ui/Table";
import { api } from "@/lib/api/client";
import { apiErrorMessage, unwrap } from "@/lib/api/errors";
import { useLoad } from "@/lib/hooks/useLoad";
import { m, roleName } from "@/messages";
import { ROLES, type DirectoryEntry, type Member, type Role } from "./types";

type Props = { projectId: string; canEdit: boolean };

export function MembersPanel({ projectId, canEdit }: Props) {
  const members = useLoad(
    () =>
      api
        .GET("/api/v1/projects/{project_id}/members", {
          params: { path: { project_id: projectId } },
        })
        .then((r) => unwrap(r)),
    [projectId],
  );
  const directory = useLoad(
    () =>
      canEdit
        ? api.GET("/api/v1/users/directory").then((r) => unwrap(r))
        : Promise.resolve([] as DirectoryEntry[]),
    [canEdit],
  );
  const [draft, setDraft] = useState<Member[] | null>(null);
  const [pickedUser, setPickedUser] = useState("");
  const [pickedRole, setPickedRole] = useState<Role>("editor");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  const rows = draft ?? members.data ?? [];
  const candidates = (directory.data ?? []).filter((u) => !rows.some((r) => r.user_id === u.id));
  const picked = candidates.find((u) => u.id === pickedUser);
  const pickedIsCustomer = picked?.account_type === "customer";

  function setRole(userId: string, role: Role) {
    setDraft(rows.map((r) => (r.user_id === userId ? { ...r, role } : r)));
    setSaved(false);
  }

  function remove(userId: string) {
    setDraft(rows.filter((r) => r.user_id !== userId));
    setSaved(false);
  }

  function add() {
    if (!picked) return;
    const role: Role = picked.account_type === "customer" ? "client" : pickedRole;
    setDraft([...rows, { ...picked, user_id: picked.id, role }]);
    setPickedUser("");
    setSaved(false);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.PUT("/api/v1/projects/{project_id}/members", {
        params: { path: { project_id: projectId } },
        body: rows.map((r) => ({ user_id: r.user_id, role: r.role as Role })),
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      setDraft(null);
      members.reload();
      setSaved(true);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  if (members.error) return <Alert kind="error">{members.error}</Alert>;
  if (members.loading && !draft && !members.data) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {error ? <Alert kind="error">{error}</Alert> : null}
      {saved ? <Alert kind="success">{m.projects.membersSaved}</Alert> : null}
      {rows.length === 0 ? <p className="text-muted">{m.projects.noMembers}</p> : null}
      <Table caption={m.projects.members}>
        <thead>
          <tr>
            <Th>{m.projects.memberName}</Th>
            <Th>{m.projects.memberEmail}</Th>
            <Th>{m.projects.memberType}</Th>
            <Th>{m.projects.memberRole}</Th>
            {canEdit ? <Th>{m.common.actions}</Th> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((member) => (
            <tr key={member.user_id}>
              <Td>{member.display_name}</Td>
              <Td>{member.email}</Td>
              <Td>{member.account_type === "customer" ? m.roles.customer : m.roles.internal}</Td>
              <Td>
                {canEdit && member.account_type !== "customer" ? (
                  <span aria-label={`${m.projects.memberRole}: ${member.display_name}`}>
                    <select
                      aria-label={`${m.projects.memberRole}: ${member.display_name}`}
                      value={member.role}
                      onChange={(event) => setRole(member.user_id, event.target.value as Role)}
                      className="rounded-md border border-border bg-surface px-2 py-1 text-sm"
                    >
                      {ROLES.filter((r) => r !== "client").map((r) => (
                        <option key={r} value={r}>
                          {roleName(r)}
                        </option>
                      ))}
                    </select>
                  </span>
                ) : (
                  <span aria-label={`${m.projects.memberRole}: ${member.display_name}`}>
                    {roleName(member.role)}
                  </span>
                )}
              </Td>
              {canEdit ? (
                <Td>
                  <Button variant="danger" onClick={() => remove(member.user_id)}>
                    {m.projects.remove}
                  </Button>
                </Td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </Table>
      {canEdit ? (
        <div className="flex flex-wrap items-end gap-2 rounded-md border border-border p-3">
          <div className="min-w-64 grow">
            <Select
              label={m.projects.selectUser}
              value={pickedUser}
              onChange={(event) => setPickedUser(event.target.value)}
            >
              <option value="">—</option>
              {candidates.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.display_name} ({u.email})
                </option>
              ))}
            </Select>
          </div>
          <div className="min-w-40">
            <Select
              label={m.projects.memberRole}
              value={pickedIsCustomer ? "client" : pickedRole}
              disabled={pickedIsCustomer}
              onChange={(event) => setPickedRole(event.target.value as Role)}
            >
              {ROLES.filter((r) => (pickedIsCustomer ? r === "client" : r !== "client")).map(
                (r) => (
                  <option key={r} value={r}>
                    {roleName(r)}
                  </option>
                ),
              )}
            </Select>
          </div>
          <Button variant="secondary" onClick={add} disabled={!picked}>
            {m.projects.addMember}
          </Button>
          <Button onClick={() => void save()} busy={busy} disabled={draft === null}>
            {m.projects.saveMembers}
          </Button>
        </div>
      ) : null}
    </div>
  );
}
