import type { components } from "@/lib/api/schema";
import { m } from "@/messages";

export type Me = components["schemas"]["MeResponse"];
export type NextRoute = "/mfa" | "/change-password" | "/projects";

/** Where a signed-in user must go next (spec 13: MFA first, then the forced password change). */
export function nextRoute(me: Me): NextRoute {
  if (!me.mfa_verified) return "/mfa";
  if (me.must_change_password) return "/change-password";
  return "/projects";
}

export function roleLabel(me: Me): string {
  if (me.is_admin) return m.roles.admin;
  return me.account_type === "customer" ? m.roles.customer : m.roles.internal;
}
