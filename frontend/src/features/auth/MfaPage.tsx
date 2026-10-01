"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { api } from "@/lib/api/client";
import { nextRoute, type Me } from "@/lib/session/next-route";
import { m } from "@/messages";
import { MfaEnrol } from "./MfaEnrol";
import { MfaVerify } from "./MfaVerify";

/** Second step after the password: enrol (first sign-in) or verify, then continue. */
export function MfaPage() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.GET("/api/v1/auth/me").then(
      ({ data, response }) => {
        if (cancelled) return;
        if (!data) {
          if (response.status === 401) router.replace("/login");
          else setError(m.common.loadFailed);
          return;
        }
        if (data.mfa_verified) {
          router.replace(nextRoute(data));
          return;
        }
        setMe(data);
      },
      () => {
        if (!cancelled) setError(m.common.loadFailed);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [router]);

  const done = (verified: Me) => router.replace(nextRoute(verified));

  if (error) return <Alert kind="error">{error}</Alert>;
  if (!me) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">{m.auth.mfaTitle}</h1>
      {me.mfa_enabled ? <MfaVerify onVerified={done} /> : <MfaEnrol onDone={done} />}
    </div>
  );
}
