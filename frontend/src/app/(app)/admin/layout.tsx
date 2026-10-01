"use client";

import Link from "next/link";
import { notFound, usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { cx } from "@/lib/cx";
import { useSession } from "@/lib/session/SessionProvider";
import { m } from "@/messages";

const tabs = [
  { href: "/admin/users", label: m.nav.users },
  { href: "/admin/storage", label: m.nav.storage },
];

export default function AdminLayout({ children }: { children: ReactNode }) {
  const { me } = useSession();
  const pathname = usePathname();
  if (!me.is_admin) notFound(); // non-admins see the not-found page, not a hint that /admin exists
  return (
    <div>
      <nav aria-label={m.nav.adminSections} className="mb-6 flex gap-4 border-b border-border">
        {tabs.map((tab) => {
          const current = pathname.startsWith(tab.href);
          return (
            <Link
              key={tab.href}
              href={tab.href}
              aria-current={current ? "page" : undefined}
              className={cx(
                "-mb-px border-b-2 px-1 pb-2 text-sm",
                current
                  ? "border-brand font-semibold text-brand"
                  : "border-transparent text-muted hover:text-fg",
              )}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>
      {children}
    </div>
  );
}
