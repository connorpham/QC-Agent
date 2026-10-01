import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Button } from "./Button";

it("defaults to type=button and is disabled while busy", () => {
  render(<Button busy>Save</Button>);
  const button = screen.getByRole("button", { name: "Save" });
  expect(button).toHaveAttribute("type", "button");
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("aria-busy", "true");
});
