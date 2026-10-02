import type { components } from "@/lib/api/schema";

export type Upload = components["schemas"]["UploadOut"];
export type UploadItem = components["schemas"]["UploadItemOut"];
export type UploadLimits = components["schemas"]["UploadLimitsOut"];
export type Taxonomy = components["schemas"]["TaxonomyOut"];
export type VersionSuggestion = components["schemas"]["VersionSuggestionOut"];
export type Visibility = "internal" | "shared";
export type Intent = "new" | "version";

// No endpoint exposes this set to the client, so it is duplicated here by hand. Source of
// truth: `ACTIVE_STATUSES` in `backend/app/db/models/ingestion.py`. A backend test
// (`backend/tests/db/test_models.py::test_active_statuses_matches_the_frontend_constant`)
// fails the moment the two lists diverge, as a tripwire for whoever changes the server's list.
export const ACTIVE_STATUSES = ["uploaded", "converting", "checking", "publishing"] as const;

export function isActive(status: string): boolean {
  return (ACTIVE_STATUSES as readonly string[]).includes(status);
}

export function hasActiveItems(upload: Upload): boolean {
  return upload.items.some((item) => isActive(item.status));
}
