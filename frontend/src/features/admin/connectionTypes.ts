import { m } from "@/messages";
import type { Connection, ConnectionType } from "./types";

export type ConnectionField = {
  name: string;
  label: string;
  hint?: string;
  secret?: boolean;
  multiline?: boolean;
  maxLength: number;
};

export type ConnectionTypeSpec = {
  /** Non-secret fields, in the order they appear in the dialog. */
  fields: ConnectionField[];
  /** The write-only secret, or null for a type that has none. */
  secretField: ConnectionField | null;
  defaults: Record<string, string>;
  summary: (config: Record<string, unknown>) => string;
  /** A prerequisite an administrator must satisfy outside this application, if any. */
  prereq?: string;
};

export const CONNECTION_SPECS: Record<ConnectionType, ConnectionTypeSpec> = {
  localfs: {
    fields: [
      {
        name: "root_path",
        label: m.storage.rootPath,
        hint: m.storage.rootPathHint,
        maxLength: 500,
      },
    ],
    secretField: null,
    defaults: { root_path: "." },
    summary: (config) => String(config.root_path ?? ""),
  },
  sharepoint: {
    fields: [
      {
        name: "tenant_id",
        label: m.storage.tenantId,
        hint: m.storage.tenantIdHint,
        maxLength: 200,
      },
      {
        name: "client_id",
        label: m.storage.clientId,
        hint: m.storage.clientIdHint,
        maxLength: 200,
      },
      { name: "site_id", label: m.storage.siteId, hint: m.storage.siteIdHint, maxLength: 400 },
      {
        name: "drive_id",
        label: m.storage.libraryId,
        hint: m.storage.libraryIdHint,
        maxLength: 400,
      },
    ],
    secretField: {
      name: "secret",
      label: m.storage.clientSecret,
      hint: m.storage.clientSecretHint,
      secret: true,
      maxLength: 20000,
    },
    defaults: {},
    // The list shows the library, which is the customer-visible part; tenant and client ids
    // identify the application and are not useful in a table.
    summary: (config) => String(config.drive_id ?? ""),
    prereq: m.storage.sharePointPrereq,
  },
  gdrive: {
    fields: [
      {
        name: "drive_id",
        label: m.storage.sharedDriveId,
        hint: m.storage.sharedDriveIdHint,
        maxLength: 200,
      },
    ],
    secretField: {
      name: "secret",
      label: m.storage.serviceAccountKey,
      hint: m.storage.serviceAccountKeyHint,
      secret: true,
      multiline: true,
      maxLength: 20000,
    },
    defaults: {},
    summary: (config) => String(config.drive_id ?? ""),
    prereq: m.storage.googleDrivePrereq,
  },
};

export function connectionSummary(connection: Connection): string {
  const spec = CONNECTION_SPECS[connection.type as ConnectionType];
  return spec ? spec.summary(connection.config) : "";
}

/** Tokens the health check returns that blame no single typed field: they mean an
 * administrator outside this application has not granted access yet. */
const NO_FIELD_TOKENS = new Set(["write_grant", "not_member", "versioning", "keep_forever"]);

/** The dialog label of a field a failed Test connection blamed, for the result message.
 * Returns null when the token names a prerequisite the form cannot fix (see NO_FIELD_TOKENS),
 * so the caller falls back to showing the backend's own explanation instead of pointing at
 * an input. */
export function fieldLabel(type: string, field: string | null | undefined): string | null {
  if (!field) return null;
  if (NO_FIELD_TOKENS.has(field)) return null;
  const spec = CONNECTION_SPECS[type as ConnectionType];
  if (!spec) return null;
  // The document library can be rejected either because it does not exist (drive_id) or
  // because it belongs to a different site (drive_id_wrong_site); both are fixed by
  // correcting the same input.
  const name = field === "drive_id_wrong_site" ? "drive_id" : field;
  if (spec.secretField && spec.secretField.name === name) return spec.secretField.label;
  return spec.fields.find((f) => f.name === name)?.label ?? null;
}
