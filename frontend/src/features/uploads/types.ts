import type { components } from "@/lib/api/schema";

export type Upload = components["schemas"]["UploadOut"];
export type UploadItem = components["schemas"]["UploadItemOut"];
export type UploadLimits = components["schemas"]["UploadLimitsOut"];
export type Taxonomy = components["schemas"]["TaxonomyOut"];
export type VersionSuggestion = components["schemas"]["VersionSuggestionOut"];
export type Visibility = "internal" | "shared";
export type Intent = "new" | "version";

export const ACTIVE_STATUSES = ["uploaded", "converting", "checking", "publishing"] as const;

export function isActive(status: string): boolean {
  return (ACTIVE_STATUSES as readonly string[]).includes(status);
}

export function hasActiveItems(upload: Upload): boolean {
  return upload.items.some((item) => isActive(item.status));
}
