import type { components } from "@/lib/api/schema";

export type User = components["schemas"]["UserOut"];
export type Connection = components["schemas"]["StorageConnectionOut"];
export type ConnectionType = components["schemas"]["StorageConnectionCreate"]["type"];

export const CONNECTION_TYPES: ConnectionType[] = ["localfs", "sharepoint", "gdrive"];
export const AVAILABLE_TYPES: ConnectionType[] = ["localfs", "sharepoint", "gdrive"];
