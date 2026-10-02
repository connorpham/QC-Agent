"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useId, useState, type ReactNode } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cx } from "@/lib/cx";
import { roleLabel } from "@/lib/session/next-route";
import { useSession } from "@/lib/session/SessionProvider";
import { m } from "@/messages";

type NavLink = { href: string; label: string; match: string };

/** Application frame. Below `md` the links and the user row live in a menu toggled by a
 * button (aria-expanded / aria-controls); from `md` up they are always visible. */
export function AppShell({ children }: { children: ReactNode }) {
  const { me, logout } = useSession();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const links: NavLink[] = [
    { href: "/projects", label: m.nav.projects, match: "/projects" },
    { href: "/tasks", label: m.nav.tasks, match: "/tasks" },
  ];
  if (me.is_admin) links.push({ href: "/admin/users", label: m.nav.admin, match: "/admin" });
  return (
    <div className="min-h-full">
      <header className="border-b border-border bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
          <Link href="/projects" className="min-h-10 py-2 font-semibold">
            {m.app.name}
          </Link>
          <button
            type="button"
            aria-expanded={open}
            aria-controls={menuId}
            aria-label={open ? m.nav.closeMenu : m.nav.openMenu}
            onClick={() => setOpen((o) => !o)}
            className="min-h-10 rounded-md border border-border px-3 text-sm md:hidden"
          >
            {open ? "×" : "☰"}
          </button>
          <div
            id={menuId}
            className={cx(
              "w-full flex-col gap-3 md:flex md:w-auto md:flex-1 md:flex-row md:items-center md:justify-between",
              open ? "flex" : "hidden",
            )}
          >
            <nav aria-label={m.nav.main} className="flex flex-col gap-1 md:flex-row md:gap-5">
              {links.map((link) => {
                const current = pathname.startsWith(link.match);
                return (
                  <Link
                    key={link.href}
                    href={link.href}
                    aria-current={current ? "page" : undefined}
                    onClick={() => setOpen(false)}
                    className={cx(
                      "min-h-10 py-2 text-sm",
                      current ? "font-semibold text-brand" : "text-muted hover:text-fg",
                    )}
                  >
                    {link.label}
                  </Link>
                );
              })}
            </nav>
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <span>{me.display_name}</span>
              <Badge>{roleLabel(me)}</Badge>
              <Link
                href="/change-password"
                className="text-muted hover:text-fg"
                onClick={() => setOpen(false)}
              >
                {m.nav.changePassword}
              </Link>
              <Button variant="secondary" onClick={() => void logout()}>
                {m.nav.logout}
              </Button>
            </div>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
    </div>
  );
}
