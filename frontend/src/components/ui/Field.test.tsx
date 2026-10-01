import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { Field } from "./Field";

it("associates the label, hint and error with the input", () => {
  render(<Field label="E-mail" hint="Work address" error="Required" />);
  const input = screen.getByLabelText("E-mail");
  expect(input).toHaveAccessibleDescription("Work address Required");
  expect(input).toHaveAttribute("aria-invalid", "true");
  expect(screen.getByRole("alert")).toHaveTextContent("Required");
});
