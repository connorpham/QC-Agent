"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { m } from "@/messages";

export function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/auth/login", {
        body: { email, password },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.auth.loginFailed));
        return;
      }
      router.replace("/mfa"); // enrolment or verification: the MFA page decides
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void submit(event)} className="space-y-4">
      <h1 className="text-lg font-semibold">{m.auth.loginTitle}</h1>
      {error ? <Alert kind="error">{error}</Alert> : null}
      <Field
        label={m.auth.email}
        type="email"
        autoComplete="username"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
      />
      <Field
        label={m.auth.password}
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
      />
      <Button type="submit" busy={busy} className="w-full">
        {m.auth.signIn}
      </Button>
    </form>
  );
}
