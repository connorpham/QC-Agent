import type { ReactNode } from "react";
import { vi } from "vitest";
import { SessionContext, type Session } from "@/lib/session/SessionProvider";
import type { Me } from "@/lib/session/next-route";

export const adminMe: Me = {
  id: "00000000-0000-0000-0000-00000000000a",
  email: "root@example.com",
  display_name: "Root",
  account_type: "internal",
  is_admin: true,
  mfa_enabled: true,
  mfa_verified: true,
  must_change_password: false,
};

export const memberMe: Me = {
  ...adminMe,
  id: "00000000-0000-0000-0000-00000000000b",
  email: "alice@example.com",
  display_name: "Alice",
  is_admin: false,
};

export const customerMe: Me = {
  ...memberMe,
  id: "00000000-0000-0000-0000-00000000000c",
  email: "c@client.com",
  display_name: "Cara",
  account_type: "customer",
};

/** Render `ui` inside a ready session without hitting /auth/me. */
export function withSession(ui: ReactNode, me: Me = memberMe, overrides: Partial<Session> = {}) {
  const session: Session = {
    me,
    refresh: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    ...overrides,
  };
  return {
    session,
    element: <SessionContext.Provider value={session}>{ui}</SessionContext.Provider>,
  };
}
