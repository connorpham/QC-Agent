"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/Alert";
import { api } from "@/lib/api/client";
import { m } from "@/messages";
import { ChangePasswordForm } from "./ChangePasswordForm";

/** Reachable after MFA; the forced change (must_change_password) lands here through the
 * session provider, voluntary changes through the header link. */
export function ChangePasswordPage() {
  const router = useRouter();
  const [ready, setReady] = useState(false);
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
        if (!data.mfa_verified) {
          router.replace("/mfa");
          return;
        }
        setReady(true);
      },
      () => {
        if (!cancelled) setError(m.common.loadFailed);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (error) return <Alert kind="error">{error}</Alert>;
  if (!ready) {
    return (
      <p role="status" className="text-muted">
        {m.app.loading}
      </p>
    );
  }
  return <ChangePasswordForm onChanged={() => router.replace("/projects")} />;
}
