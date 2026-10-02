import { randomBytes } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";

// Ports differ from the dev servers (3000/8000) so the suite never collides with them.
export const FRONTEND_URL = "http://localhost:3001";
export const BACKEND_URL = "http://localhost:8001";
export const DATABASE_URL =
  process.env.QC_E2E_DATABASE_URL ?? "postgresql+asyncpg://qc:qc@localhost:5434/qc_agent_e2e";

const dataRoot = mkdtempSync(path.join(tmpdir(), "qc-agent-e2e-"));

/** Environment for the backend process and the CLI: a disposable database, temporary data
 * folders and random per-run secrets (a Fernet key is 32 random bytes in base64). */
export const backendEnv: Record<string, string> = {
  DATABASE_URL,
  SESSION_SECRET: randomBytes(32).toString("hex"),
  SECRET_ENCRYPTION_KEY: randomBytes(32).toString("base64"),
  COOKIE_SECURE: "false",
  EXPOSE_DOCS: "false",
  LOCAL_STORAGE_ROOT: path.join(dataRoot, "workspace"),
  STAGING_ROOT: path.join(dataRoot, "staging"),
};

export const ADMIN_EMAIL = "e2e-admin@example.com";
export const STATE_FILE = path.join(__dirname, ".state", "admin.json");
export const SAMPLE_DOCX = path.join(__dirname, ".state", "sample.docx");
