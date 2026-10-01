import type { ReactNode } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { SessionProvider } from "@/lib/session/SessionProvider";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <SessionProvider>
      <AppShell>{children}</AppShell>
    </SessionProvider>
  );
}
