"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";

/** Controller ruling A2: the client's 401 redirect handler is deliberately skipped for every
 * /api/v1/auth/* path, so a 401 here (the session expired mid-form) is handled locally. */
export function ChangePasswordForm({ onChanged }: { onChanged: () => void }) {
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (next !== confirm) {
      setError(m.auth.passwordsDiffer);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const { response, error: apiError } = await api.POST("/api/v1/auth/change-password", {
        body: { current_password: current, new_password: next },
      });
      if (response.status === 401) {
        router.replace("/login");
        return;
      }
      if (!response.ok) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      onChanged();
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <h1 className="text-lg font-semibold">{m.auth.changePasswordTitle}</h1>
      <p className="text-sm text-muted">{m.auth.changePasswordIntro}</p>
      {error ? <Alert kind="error">{error}</Alert> : null}
      <Field
        label={m.auth.currentPassword}
        type="password"
        autoComplete="current-password"
        required
        value={current}
        onChange={(event) => setCurrent(event.target.value)}
      />
      <Field
        label={m.auth.newPassword}
        type="password"
        autoComplete="new-password"
        required
        minLength={12}
        value={next}
        onChange={(event) => setNext(event.target.value)}
      />
      <Field
        label={m.auth.confirmPassword}
        type="password"
        autoComplete="new-password"
        required
        minLength={12}
        value={confirm}
        onChange={(event) => setConfirm(event.target.value)}
      />
      <Button type="submit" busy={busy} className="w-full">
        {m.auth.changePasswordAction}
      </Button>
    </form>
  );
}
