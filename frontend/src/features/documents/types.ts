import type { components } from "@/lib/api/schema";

export type Document = components["schemas"]["DocumentOut"];
export type DocumentVersion = components["schemas"]["DocumentVersionOut"];
export type DocumentContent = components["schemas"]["DocumentContentOut"];
export type GapReportData = components["schemas"]["GapReportOut"];
export type Taxonomy = components["schemas"]["TaxonomyOut"];

export const EDITOR_ROLES = ["owner", "editor"] as const;
export const INTERNAL_ROLES = ["owner", "editor", "viewer"] as const;

export function canEdit(role: string): boolean {
  return (EDITOR_ROLES as readonly string[]).includes(role);
}

export function isInternal(role: string): boolean {
  return (INTERNAL_ROLES as readonly string[]).includes(role);
}

export function originalUrl(documentId: string, version: number): string {
  return `/api/v1/documents/${documentId}/versions/${version}/original`;
}

export function markdownUrl(documentId: string, version: number): string {
  return `/api/v1/documents/${documentId}/versions/${version}/markdown`;
}
