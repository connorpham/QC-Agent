import { m } from "@/messages";
import type { UploadLimits } from "./types";

const ALIASES: Record<string, string> = { htm: "html" };
const MB = 1024 * 1024;

export function extensionOf(name: string): string | null {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot === name.length - 1) return null;
  const ext = name.slice(dot + 1).toLowerCase();
  return ALIASES[ext] ?? ext;
}

/** The reason a file must not be sent, or null. Mirrors the backend's intake rules so an
 * obvious mistake fails in the row instead of after a 50 MB upload. */
export function guardFile(file: File, limits: UploadLimits): string | null {
  const ext = extensionOf(file.name);
  if (ext === null || !limits.allowed_extensions.includes(ext)) {
    return m.uploads.unsupportedType(limits.allowed_extensions.join(", "));
  }
  if (file.size > limits.max_file_mb * MB) return m.uploads.tooLarge(limits.max_file_mb);
  return null;
}

export function batchGuard(files: File[], limits: UploadLimits): string | null {
  const total = files.reduce((sum, file) => sum + file.size, 0);
  return total > limits.max_batch_mb * MB ? m.uploads.batchTooLarge(limits.max_batch_mb) : null;
}
