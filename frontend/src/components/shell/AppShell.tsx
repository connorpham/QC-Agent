"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cx } from "@/lib/cx";
import { roleLabel } from "@/lib/session/next-route";
import { useSession } from "@/lib/session/SessionProvider";
import { m } from "@/messages";

type NavLink = { href: string; label: string; match: string };

export function AppShell({ children }: { children: ReactNode }) {
  const { me, logout } = useSession();
  const pathname = usePathname();
  const links: NavLink[] = [{ href: "/projects", label: m.nav.projects, match: "/projects" }];
  if (me.is_admin) links.push({ href: "/admin/users", label: m.nav.admin, match: "/admin" });
  return (
    <div className="min-h-full">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <nav aria-label={m.nav.main} className="flex items-center gap-5">
            <Link href="/projects" className="font-semibold">
              {m.app.name}
            </Link>
            {links.map((link) => {
              const current = pathname.startsWith(link.match);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  aria-current={current ? "page" : undefined}
                  className={cx(
                    "text-sm",
                    current ? "font-semibold text-brand" : "text-muted hover:text-fg",
                  )}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>
          <div className="flex items-center gap-3 text-sm">
            <span>{me.display_name}</span>
            <Badge>{roleLabel(me)}</Badge>
            <Link href="/change-password" className="text-muted hover:text-fg">
              {m.nav.changePassword}
            </Link>
            <Button variant="secondary" onClick={() => void logout()}>
              {m.nav.logout}
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
