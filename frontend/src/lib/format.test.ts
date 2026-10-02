import { expect, it } from "vitest";
import { formatBytes, formatDate } from "./format";

it("formats byte counts for people", () => {
  expect(formatBytes(0)).toBe("0 B");
  expect(formatBytes(999)).toBe("999 B");
  expect(formatBytes(1024)).toBe("1.0 KB");
  expect(formatBytes(1536)).toBe("1.5 KB");
  expect(formatBytes(52_428_800)).toBe("50.0 MB");
  expect(formatBytes(1_073_741_824)).toBe("1.0 GB");
});

it("formats dates in the en-GB style the rest of the UI uses", () => {
  expect(formatDate("2026-10-01T10:00:00+00:00")).toBe("01/10/2026");
});
