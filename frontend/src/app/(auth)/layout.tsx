import type { ReactNode } from "react";
import { m } from "@/messages";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-md rounded-lg border border-border bg-surface p-6 shadow-sm">
        <p className="mb-4 text-sm font-semibold text-muted">{m.app.name}</p>
        {children}
      </div>
    </main>
  );
}
