"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { m } from "@/messages";

type Props = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
};

/** Native <dialog> opened with showModal(): the browser traps focus and closes on Escape,
 * which fires `close`, so the parent only has to flip `open` in `onClose`. */
export function Dialog({ open, title, onClose, children, footer }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    else if (!open && element.open) element.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onClose={onClose}
      className="m-auto w-full max-w-lg rounded-lg border border-border bg-surface p-0 text-fg shadow-xl backdrop:bg-black/40"
    >
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <h2 id={titleId} className="text-lg font-semibold">
          {title}
        </h2>
        <button
          type="button"
          onClick={onClose}
          aria-label={m.common.close}
          className="rounded px-2 text-xl leading-none text-muted hover:text-fg"
        >
          ×
        </button>
      </div>
      <div className="px-5 py-4">{children}</div>
      {footer ? (
        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">{footer}</div>
      ) : null}
    </dialog>
  );
}
