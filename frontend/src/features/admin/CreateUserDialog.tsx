"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Dialog } from "@/components/ui/Dialog";
import { Field } from "@/components/ui/Field";
import { Select } from "@/components/ui/Select";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";
import type { User } from "./types";

type Props = { onClose: () => void; onCreated: (user: User, temporaryPassword: string) => void };

export function CreateUserDialog({ onClose, onCreated }: Props) {
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [accountType, setAccountType] = useState<"internal" | "customer">("internal");
  const [isAdmin, setIsAdmin] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const customer = accountType === "customer";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/users", {
        body: {
          email,
          display_name: displayName,
          account_type: accountType,
          is_admin: customer ? false : isAdmin,
        },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onCreated(data.user, data.temporary_password);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open title={m.users.newUser} onClose={onClose}>
      <form onSubmit={(event) => void submit(event)} className="space-y-4">
        {error ? <Alert kind="error">{error}</Alert> : null}
        <Field
          label={m.users.email}
          type="email"
          required
          maxLength={320}
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
        <Field
          label={m.users.displayName}
          required
          maxLength={200}
          value={displayName}
          onChange={(event) => setDisplayName(event.target.value)}
        />
        <Select
          label={m.users.accountType}
          value={accountType}
          onChange={(event) => setAccountType(event.target.value as "internal" | "customer")}
        >
          <option value="internal">{m.users.internal}</option>
          <option value="customer">{m.users.customer}</option>
        </Select>
        <Checkbox
          label={m.users.isAdmin}
          checked={customer ? false : isAdmin}
          disabled={customer}
          onChange={(event) => setIsAdmin(event.target.checked)}
        />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onClose}>
            {m.common.cancel}
          </Button>
          <Button type="submit" busy={busy}>
            {m.common.create}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
