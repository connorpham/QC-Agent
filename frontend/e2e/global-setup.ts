import { execFileSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { ADMIN_EMAIL, STATE_FILE, backendEnv } from "./env";

/** Runs after the web servers are up (Playwright starts them first): the database is migrated,
 * so the CLI can create the first administrator. */
export default function globalSetup(): void {
  const output = execFileSync(
    "uv",
    [
      "run",
      "--directory",
      path.join(__dirname, "..", "..", "backend"),
      "qc-agent",
      "create-admin",
      "--email",
      ADMIN_EMAIL,
      "--name",
      "E2E Admin",
    ],
    { encoding: "utf8", env: { ...process.env, ...backendEnv } },
  );
  const match = /Temporary password \(shown once\): (\S+)/.exec(output);
  if (!match) throw new Error(`create-admin did not print a temporary password:\n${output}`);
  mkdirSync(path.dirname(STATE_FILE), { recursive: true });
  writeFileSync(STATE_FILE, JSON.stringify({ email: ADMIN_EMAIL, password: match[1] }));
}
