import type { components } from "@/lib/api/schema";

export type Project = components["schemas"]["ProjectOut"];
export type Member = components["schemas"]["MemberOut"];
export type Role = components["schemas"]["MemberIn"]["role"];
export type AvailableConnection = components["schemas"]["StorageConnectionAvailable"];
export type DirectoryEntry = components["schemas"]["UserDirectoryEntry"];

export const INTERNAL_ROLES = ["owner", "editor", "viewer"] as const;
export const ROLES: Role[] = ["owner", "editor", "viewer", "client"];
