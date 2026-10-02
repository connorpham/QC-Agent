import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type Ref,
  type TextareaHTMLAttributes,
} from "react";
import { cx } from "@/lib/cx";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "id"> & {
  label: string;
  hint?: string;
  error?: string | null;
  /** Render a <textarea> instead of an <input>, for a multi-line value such as a JSON key. */
  multiline?: boolean;
};

export const inputClass =
  "block w-full rounded-md border border-border bg-surface px-3 py-1.5 text-sm text-fg " +
  "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:opacity-60";

/** Forwards a ref to the underlying <input>/<textarea>, so a caller can read an uncontrolled
 * field (e.g. a secret that must never be reflected into a controlled value and so never land
 * in the DOM's attribute serialization) directly from the element at submit time. */
export const Field = forwardRef<HTMLInputElement | HTMLTextAreaElement, Props>(function Field(
  { label, hint, error, className, multiline, ...input },
  ref,
) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {multiline ? (
        <textarea
          id={id}
          ref={ref as Ref<HTMLTextAreaElement>}
          aria-describedby={describedBy || undefined}
          aria-invalid={error ? true : undefined}
          className={cx(inputClass, className)}
          rows={6}
          spellCheck={false}
          {...(input as TextareaHTMLAttributes<HTMLTextAreaElement>)}
        />
      ) : (
        <input
          id={id}
          ref={ref as Ref<HTMLInputElement>}
          aria-describedby={describedBy || undefined}
          aria-invalid={error ? true : undefined}
          className={cx(inputClass, className)}
          {...input}
        />
      )}
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
});
