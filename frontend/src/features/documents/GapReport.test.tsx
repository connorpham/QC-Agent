import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { mockFetch } from "@/test/fetch-mock";
import { GapReport } from "./GapReport";

const PID = "11111111-1111-1111-1111-111111111111";
const report = {
  qc_agent: 2,
  project: { slug: "demo", name: "Demo" },
  generated_at: "2026-10-02T09:30:00+00:00",
  required_total: 10,
  required_present: 2,
  completeness: 0.2,
  folders: [
    {
      id: "requirements",
      dir: "02-requirements",
      stage: "What",
      doc_types: [
        {
          doc_type: "brd",
          title: "Business Requirements Document",
          required: true,
          status: "stub",
          documents: 0,
        },
        {
          doc_type: "srs",
          title: "Software Requirements Specification",
          required: true,
          status: "present",
          documents: 1,
        },
        {
          doc_type: "use-cases",
          title: "Use Cases",
          required: false,
          status: "missing",
          documents: 0,
        },
      ],
    },
  ],
};

it("shows completeness and each type's status per folder", async () => {
  mockFetch([{ path: `/api/v1/projects/${PID}/gap-report`, body: report }]);
  render(<GapReport projectId={PID} />);
  expect(await screen.findByText("2 of 10 required types present (20%)")).toBeInTheDocument();
  const table = screen.getByRole("table", { name: "02-requirements (What)" });
  const rows = within(table).getAllByRole("row").slice(1);
  expect(rows).toHaveLength(3);
  expect(within(rows[0]).getByText("Placeholder")).toBeInTheDocument();
  expect(within(rows[0]).getByText("Required")).toBeInTheDocument();
  expect(within(rows[1]).getByText("Present")).toBeInTheDocument();
  expect(within(rows[1]).getByText("1")).toBeInTheDocument();
  expect(within(rows[2]).getByText("Missing")).toBeInTheDocument();
  expect(within(rows[2]).getByText("Optional")).toBeInTheDocument();
  expect(screen.getByRole("progressbar", { name: "Gap report" })).toHaveAttribute(
    "aria-valuenow",
    "20",
  );
});

it("shows the API error", async () => {
  mockFetch([
    {
      path: `/api/v1/projects/${PID}/gap-report`,
      status: 403,
      body: { detail: "You do not have access to this action." },
    },
  ]);
  render(<GapReport projectId={PID} />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "You do not have access to this action.",
  );
});
