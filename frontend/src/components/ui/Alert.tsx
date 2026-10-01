import type { ReactNode } from "react";
import { cx } from "@/lib/cx";

type Kind = "error" | "success" | "info";

const styles: Record<Kind, string> = {
  error: "border-danger/40 bg-danger/10 text-danger",
  success: "border-success/40 bg-success/10 text-success",
  info: "border-border bg-bg text-fg",
};

export function Alert({
  kind,
  children,
  className,
}: {
  kind: Kind;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      role={kind === "error" ? "alert" : "status"}
      className={cx("rounded-md border px-3 py-2 text-sm", styles[kind], className)}
    >
      {children}
    </div>
  );
}
