import { Badge } from "@/components/ui/Badge";
import { m } from "@/messages";

const TONES: Record<string, "neutral" | "success" | "warning" | "danger"> = {
  published: "success",
  failed: "danger",
  needs_confirmation: "warning",
};

/** Upload-item status as a labelled badge (text, never colour alone). */
export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={TONES[status] ?? "neutral"}>{m.uploads.status[status] ?? status}</Badge>;
}
