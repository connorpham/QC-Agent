import type { ButtonHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

type Variant = "primary" | "secondary" | "danger";
type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean };

const variants: Record<Variant, string> = {
  primary: "bg-brand text-brand-fg hover:opacity-90",
  secondary: "border border-border bg-surface text-fg hover:bg-bg",
  danger: "bg-danger text-white hover:opacity-90",
};

export function Button({
  variant = "primary",
  busy = false,
  disabled,
  className,
  type = "button",
  children,
  ...rest
}: Props) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium",
        "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand",
        "disabled:cursor-not-allowed disabled:opacity-60",
        variants[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
