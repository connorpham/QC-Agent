"use client";

import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "@/lib/cx";

export type TabItem = { id: string; label: string; render: () => ReactNode };

type Props = { label: string; items: TabItem[]; value: string; onChange: (id: string) => void };

/** WAI-ARIA tabs: one tabstop (roving tabIndex), arrow keys / Home / End move and select,
 * the active panel is labelled by its tab. Only the active panel is rendered. */
export function Tabs({ label, items, value, onChange }: Props) {
  const prefix = useId();
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const active = items.find((item) => item.id === value) ?? items[0];
  if (!active) return null;

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const targets: Record<string, number> = {
      ArrowRight: index + 1,
      ArrowLeft: index - 1,
      Home: 0,
      End: items.length - 1,
    };
    const target = targets[event.key];
    if (target === undefined) return;
    event.preventDefault();
    const next = items[(target + items.length) % items.length];
    onChange(next.id);
    refs.current[next.id]?.focus();
  }

  return (
    <>
      <div
        role="tablist"
        aria-label={label}
        className="mb-6 flex gap-4 overflow-x-auto border-b border-border"
      >
        {items.map((item, index) => {
          const selected = item.id === active.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              id={`${prefix}-tab-${item.id}`}
              aria-selected={selected}
              aria-controls={`${prefix}-panel-${item.id}`}
              tabIndex={selected ? 0 : -1}
              ref={(element) => {
                refs.current[item.id] = element;
              }}
              onClick={() => onChange(item.id)}
              onKeyDown={(event) => onKeyDown(event, index)}
              className={cx(
                "-mb-px min-h-10 shrink-0 border-b-2 px-1 pb-2 text-sm",
                selected
                  ? "border-brand font-semibold text-brand"
                  : "border-transparent text-muted hover:text-fg",
              )}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      <div
        role="tabpanel"
        id={`${prefix}-panel-${active.id}`}
        aria-labelledby={`${prefix}-tab-${active.id}`}
      >
        {active.render()}
      </div>
    </>
  );
}
