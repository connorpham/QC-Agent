"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { Alert } from "@/components/ui/Alert";
import { Button } from "@/components/ui/Button";
import { api, setUnauthorizedHandler } from "@/lib/api/client";
import { m } from "@/messages";
import { nextRoute, type Me } from "./next-route";

export type Session = { me: Me; refresh: () => Promise<void>; logout: () => Promise<void> };

export const SessionContext = createContext<Session | null>(null);

/** Route guard for the signed-in area: loads /auth/me once and renders children only for a
 * complete session (MFA verified, no forced password change); otherwise redirects. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const { data, response } = await api.GET("/api/v1/auth/me");
      if (!data) {
        if (response.status === 401) router.replace("/login");
        else setError(m.common.loadFailed);
        return;
      }
      const next = nextRoute(data);
      if (next !== "/projects") {
        router.replace(next);
        return;
      }
      setError(null);
      setMe(data);
    } catch {
      setError(m.common.loadFailed);
    }
  }, [router]);

  useEffect(() => {
    // refresh() sets state asynchronously (inside its own .then/.catch), not synchronously
    // within this effect body; the rule can't see through the indirection.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  useEffect(() => {
    setUnauthorizedHandler(() => router.replace("/login"));
    return () => setUnauthorizedHandler(null);
  }, [router]);

  const logout = useCallback(async () => {
    await api.POST("/api/v1/auth/logout");
    router.replace("/login");
  }, [router]);

  if (error) {
    return (
      <div className="p-6">
        <Alert kind="error">
          {error}{" "}
          <Button variant="secondary" onClick={() => void refresh()}>
            {m.common.retry}
          </Button>
        </Alert>
      </div>
    );
  }
  if (!me) {
    return (
      <p role="status" className="p-6 text-muted">
        {m.app.loading}
      </p>
    );
  }
  return (
    <SessionContext.Provider value={{ me, refresh, logout }}>{children}</SessionContext.Provider>
  );
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}
