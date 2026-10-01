"use client";

import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import type { Me } from "@/lib/session/next-route";
import { m } from "@/messages";

export function MfaVerify({ onVerified }: { onVerified: (me: Me) => void }) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/auth/mfa/verify", {
        body: { code },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.auth.invalidCode));
        return;
      }
      onVerified(data);
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <p className="text-sm text-muted">{m.auth.verifyIntro}</p>
      {error ? <Alert kind="error">{error}</Alert> : null}
      <Field
        label={m.auth.codeOrRecovery}
        autoComplete="one-time-code"
        required
        value={code}
        onChange={(event) => setCode(event.target.value)}
      />
      <Button type="submit" busy={busy} className="w-full">
        {m.auth.verify}
      </Button>
    </form>
  );
}
