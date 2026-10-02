import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { expect, it } from "vitest";
import { Tabs } from "./Tabs";

function Probe() {
  const [tab, setTab] = useState("one");
  return (
    <Tabs
      label="Demo"
      value={tab}
      onChange={setTab}
      items={[
        { id: "one", label: "One", render: () => <p>First panel</p> },
        { id: "two", label: "Two", render: () => <p>Second panel</p> },
        { id: "three", label: "Three", render: () => <p>Third panel</p> },
      ]}
    />
  );
}

it("renders tablist, tab and tabpanel with the ARIA wiring and switches on click", async () => {
  render(<Probe />);
  const list = screen.getByRole("tablist", { name: "Demo" });
  const one = screen.getByRole("tab", { name: "One" });
  const two = screen.getByRole("tab", { name: "Two" });
  expect(list).toContainElement(one);
  expect(one).toHaveAttribute("aria-selected", "true");
  expect(two).toHaveAttribute("aria-selected", "false");
  expect(two).toHaveAttribute("tabindex", "-1");
  const panel = screen.getByRole("tabpanel", { name: "One" });
  expect(panel).toHaveTextContent("First panel");
  expect(one).toHaveAttribute("aria-controls", panel.id);
  await userEvent.click(two);
  expect(screen.getByRole("tabpanel", { name: "Two" })).toHaveTextContent("Second panel");
  expect(screen.queryByText("First panel")).not.toBeInTheDocument();
});

it("moves with arrow keys, Home and End and wraps around", async () => {
  render(<Probe />);
  const one = screen.getByRole("tab", { name: "One" });
  one.focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Two" })).toHaveFocus();
  expect(screen.getByRole("tabpanel", { name: "Two" })).toBeInTheDocument();
  await userEvent.keyboard("{End}");
  expect(screen.getByRole("tab", { name: "Three" })).toHaveFocus();
  await userEvent.keyboard("{ArrowRight}");
  expect(one).toHaveFocus(); // wraps
  await userEvent.keyboard("{ArrowLeft}");
  expect(screen.getByRole("tab", { name: "Three" })).toHaveFocus();
  await userEvent.keyboard("{Home}");
  expect(one).toHaveFocus();
});
