import { useId, type InputHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  label: string;
  hint?: string;
  error?: string | null;
};

export const inputClass =
  "block w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-60";

export function Field({ label, hint, error, className, ...input }: Props) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      <input
        id={id}
        aria-describedby={describedBy || undefined}
        aria-invalid={error ? true : undefined}
        className={cx(inputClass, className)}
        {...input}
      />
      {hint ? (
        <p id={hintId} className="text-xs text-muted">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
