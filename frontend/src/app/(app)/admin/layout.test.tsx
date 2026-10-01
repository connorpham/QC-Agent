import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { adminMe, memberMe, withSession } from "@/test/session";
import AdminLayout from "./layout";

const { notFound } = vi.hoisted(() => ({ notFound: vi.fn() }));
vi.mock("next/navigation", () => ({
  notFound,
  usePathname: () => "/admin/users",
}));

it("renders the admin tabs for administrators", () => {
  render(withSession(<AdminLayout>child</AdminLayout>, adminMe).element);
  expect(screen.getByRole("link", { name: "Users" })).toHaveAttribute("href", "/admin/users");
  expect(screen.getByRole("link", { name: "Storage" })).toHaveAttribute("href", "/admin/storage");
  expect(notFound).not.toHaveBeenCalled();
});

it("shows the not-found page to everyone else", () => {
  render(withSession(<AdminLayout>child</AdminLayout>, memberMe).element);
  expect(notFound).toHaveBeenCalled();
});
