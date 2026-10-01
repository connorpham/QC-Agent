"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { m } from "@/messages";

type Props = { email: string; password: string; onClose: () => void };

/** The only place a temporary password is ever shown; nothing is kept once it closes.
 * Dialog's own header button already provides the "Close" affordance (aria-label
 * m.common.close), so no duplicate footer button with the same accessible name is added. */
export function TemporaryPasswordDialog({ email, password, onClose }: Props) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(password);
    setCopied(true);
  }
  return (
    <Dialog open title={m.users.tempPasswordTitle} onClose={onClose}>
      <p className="text-sm text-muted">{m.users.tempPasswordIntro}</p>
      <p className="mt-3 text-sm font-medium">{m.users.tempPasswordFor(email)}</p>
      <div className="mt-1 flex items-center gap-2">
        <code className="rounded-md border border-border bg-bg px-3 py-2 font-mono text-base">
          {password}
        </code>
        <Button variant="secondary" onClick={() => void copy()}>
          {copied ? m.common.copied : m.common.copy}
        </Button>
      </div>
    </Dialog>
  );
}
