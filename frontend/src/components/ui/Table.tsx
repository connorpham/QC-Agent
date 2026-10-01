import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

export function Table({ children, caption }: { children: ReactNode; caption?: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        {children}
      </table>
    </div>
  );
}

export function Th({ children }: { children?: ReactNode }) {
  return (
    <th scope="col" className="border-b border-border bg-bg px-3 py-2 font-medium text-muted">
      {children}
    </th>
  );
}

export function Td({ children, className }: { children?: ReactNode; className?: string }) {
  return (
    <td className={cx("border-b border-border px-3 py-2 align-middle", className)}>{children}</td>
  );
}
