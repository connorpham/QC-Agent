"use client";

import QRCode from "qrcode";
import { useEffect, useState, type FormEvent } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { api } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import type { Me } from "@/lib/session/next-route";
import { m } from "@/messages";
import { RecoveryCodes } from "./RecoveryCodes";

type Step =
  | { kind: "loading" }
  | { kind: "scan"; secret: string; qr: string | null }
  | { kind: "codes"; codes: string[] };

export function MfaEnrol({ onDone }: { onDone: (me: Me) => void }) {
  const [step, setStep] = useState<Step>({ kind: "loading" });
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function start() {
      const { data, error: apiError } = await api.POST("/api/v1/auth/mfa/enroll");
      if (cancelled) return;
      if (!data) {
        setError(apiErrorMessage(apiError, m.common.requestFailed));
        return;
      }
      let qr: string | null = null;
      try {
        qr = await QRCode.toDataURL(data.otpauth_uri, { width: 192, margin: 1 });
      } catch {
        qr = null; // the setup key below still works
      }
      if (!cancelled) setStep({ kind: "scan", secret: data.secret, qr });
    }
    start().catch(() => {
      if (!cancelled) setError(m.common.requestFailed);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function confirm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const { data, error: apiError } = await api.POST("/api/v1/auth/mfa/confirm", {
        body: { code },
      });
      if (!data) {
        setError(apiErrorMessage(apiError, m.auth.invalidCode));
        return;
      }
      setStep({ kind: "codes", codes: data.recovery_codes });
    } catch {
      setError(m.common.requestFailed);
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    const { data } = await api.GET("/api/v1/auth/me");
    if (data) onDone(data);
  }

  if (step.kind === "codes") {
    return <RecoveryCodes codes={step.codes} onAcknowledged={() => void finish()} />;
  }
  return (
    <form onSubmit={(event) => void confirm(event)} className="space-y-4">
      <p className="text-sm text-muted">{m.auth.enrolIntro}</p>
      {error ? <Alert kind="error">{error}</Alert> : null}
      {step.kind === "loading" ? (
        <p role="status" className="text-muted">
          {m.app.loading}
        </p>
      ) : (
        <>
          {step.qr ? (
            // eslint-disable-next-line @next/next/no-img-element -- a data URL; next/image adds nothing
            <img
              src={step.qr}
              alt={m.auth.qrAlt}
              width={192}
              height={192}
              className="rounded border border-border bg-white p-2"
            />
          ) : null}
          <Field
            label={m.auth.setupKey}
            readOnly
            value={step.secret}
            className="font-mono"
            onFocus={(event) => event.currentTarget.select()}
          />
          <Field
            label={m.auth.code}
            inputMode="numeric"
            autoComplete="one-time-code"
            required
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
          <Button type="submit" busy={busy} className="w-full">
            {m.auth.confirm}
          </Button>
        </>
      )}
    </form>
  );
}
