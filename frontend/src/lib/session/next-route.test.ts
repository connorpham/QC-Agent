import { expect, it } from "vitest";
import { adminMe, customerMe, memberMe } from "@/test/session";
import { nextRoute, roleLabel } from "./next-route";

it("sends unverified sessions to MFA, then to the password change, then to projects", () => {
  expect(nextRoute({ ...memberMe, mfa_verified: false })).toBe("/mfa");
  expect(nextRoute({ ...memberMe, mfa_verified: false, must_change_password: true })).toBe("/mfa");
  expect(nextRoute({ ...memberMe, must_change_password: true })).toBe("/change-password");
  expect(nextRoute(memberMe)).toBe("/projects");
});

it("labels roles", () => {
  expect(roleLabel(adminMe)).toBe("Administrator");
  expect(roleLabel(memberMe)).toBe("Team member");
  expect(roleLabel(customerMe)).toBe("Customer");
});
