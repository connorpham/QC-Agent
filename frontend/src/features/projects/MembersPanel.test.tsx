import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { MembersPanel } from "./MembersPanel";

const PID = "11111111-1111-1111-1111-111111111111";
const owner = {
  user_id: "u-owner",
  email: "owner@example.com",
  display_name: "Owner",
  account_type: "internal",
  role: "owner",
};
const directory = [
  { id: "u-owner", email: "owner@example.com", display_name: "Owner", account_type: "internal" },
  { id: "u-ed", email: "editor@example.com", display_name: "Editor", account_type: "internal" },
  { id: "u-cara", email: "c@client.com", display_name: "Cara", account_type: "customer" },
];

it("adds a member, forces customers to the client role and saves the full list", async () => {
  const f = mockFetch([
    { path: `/api/v1/projects/${PID}/members`, body: [owner] },
    { path: "/api/v1/users/directory", body: directory },
    {
      method: "PUT",
      path: `/api/v1/projects/${PID}/members`,
      body: [owner, { ...directory[2], user_id: "u-cara", role: "client" }],
    },
  ]);
  render(<MembersPanel projectId={PID} canEdit />);
  expect(await screen.findByRole("cell", { name: "Owner" })).toBeInTheDocument();
  const picker = screen.getByLabelText("User");
  expect(within(picker).queryByRole("option", { name: /owner@example.com/ })).toBeNull();
  await userEvent.selectOptions(picker, "u-cara");
  const roleSelect = screen.getByLabelText("Role");
  expect(roleSelect).toHaveValue("client");
  expect(roleSelect).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Add member" }));
  expect(screen.getByRole("cell", { name: "Cara" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Save members" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Members saved.");
  expect(await f.body(2)).toEqual([
    { user_id: "u-owner", role: "owner" },
    { user_id: "u-cara", role: "client" },
  ]);
});

it("is read-only for non-owners and surfaces a 422", async () => {
  mockFetch([
    { path: `/api/v1/projects/${PID}/members`, body: [owner] },
    { path: "/api/v1/users/directory", body: directory },
    {
      method: "PUT",
      path: `/api/v1/projects/${PID}/members`,
      status: 422,
      body: { detail: "A project needs at least one owner." },
    },
  ]);
  const readOnly = render(<MembersPanel projectId={PID} canEdit={false} />);
  expect(await screen.findByRole("cell", { name: "Owner" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Save members" })).not.toBeInTheDocument();
  readOnly.unmount();
  render(<MembersPanel projectId={PID} canEdit />);
  await userEvent.click(await screen.findByRole("button", { name: "Remove" }));
  await userEvent.click(screen.getByRole("button", { name: "Save members" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("A project needs at least one owner.");
});
