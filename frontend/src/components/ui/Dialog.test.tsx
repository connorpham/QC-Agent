import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Dialog } from "./Dialog";

it("opens as a modal with an accessible name and reports close", async () => {
  const onClose = vi.fn();
  render(
    <Dialog open title="Create project" onClose={onClose}>
      <input aria-label="Name" />
    </Dialog>,
  );
  const dialog = screen.getByRole("dialog", { name: "Create project" });
  expect(dialog).toBeVisible();
  expect((dialog as HTMLDialogElement).open).toBe(true);
  await userEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalledTimes(1);
});
