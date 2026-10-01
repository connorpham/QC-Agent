"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import type { Me } from "@/lib/session/next-route";
import { m } from "@/messages";

async function signedIn(): Promise<boolean> {
  return (await api.GET("/api/v1/auth/me")).response.ok;
}

/** Controller ruling A2: the client's 401 redirect handler is deliberately skipped for every
 * /api/v1/auth/* path, so a 401 here is handled locally. This endpoint answers 401 both for a
 * wrong code and for a session that has gone, so the session is re-checked before signing the
 * user out — a typo must not throw them back to the sign-in page. */
export function MfaVerify({ onVerified }: { onVerified: (me: Me) => void }) {
  const router = useRouter();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const {
        data,
        response,
        error: apiError,
      } = await api.POST("/api/v1/auth/mfa/verify", {
        body: { code },
      });
      if (!data) {
        if (response.status === 401 && !(await signedIn())) {
          router.replace("/login");
          return;
        }
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
