"use client";

import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { m } from "@/messages";

/** Shown exactly once, right after enrolment; nothing is persisted on the client. */
export function RecoveryCodes({
  codes,
  onAcknowledged,
}: {
  codes: string[];
  onAcknowledged: () => void;
}) {
  const [acknowledged, setAcknowledged] = useState(false);
  const [copied, setCopied] = useState(false);
  const text = codes.join("\n") + "\n";

  async function copy() {
    if (!navigator.clipboard) return;
    await navigator.clipboard.writeText(text);
    setCopied(true);
  }

  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "qc-agent-recovery-codes.txt";
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold">{m.auth.recoveryTitle}</h2>
      <p className="text-sm text-muted">{m.auth.recoveryIntro}</p>
      <ul className="grid grid-cols-2 gap-1 rounded-md border border-border bg-bg p-3 font-mono text-sm">
        {codes.map((recoveryCode) => (
          <li key={recoveryCode}>{recoveryCode}</li>
        ))}
      </ul>
      <div className="flex gap-2">
        <Button variant="secondary" onClick={() => void copy()}>
          {copied ? m.common.copied : m.auth.copyCodes}
        </Button>
        <Button variant="secondary" onClick={download}>
          {m.auth.downloadCodes}
        </Button>
      </div>
      <Checkbox
        label={m.auth.recoveryAck}
        checked={acknowledged}
        onChange={(event) => setAcknowledged(event.target.checked)}
      />
      <Button className="w-full" disabled={!acknowledged} onClick={onAcknowledged}>
        {m.auth.continue}
      </Button>
    </div>
  );
}
