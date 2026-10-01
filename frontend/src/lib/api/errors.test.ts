import { expect, it } from "vitest";
import { apiErrorMessage, unwrap } from "./errors";

it("reads string, list and pydantic details, else the fallback", () => {
  expect(apiErrorMessage({ detail: "Too many attempts. Try again later." }, "x")).toBe(
    "Too many attempts. Try again later.",
  );
  expect(apiErrorMessage({ detail: ["Too short.", "Add a digit."] }, "x")).toBe(
    "Too short. Add a digit.",
  );
  // pydantic prefixes a validator's message; the prefix is noise for the reader.
  expect(
    apiErrorMessage(
      { detail: [{ loc: ["body", "name"], msg: "Value error, Project name is required." }] },
      "x",
    ),
  ).toBe("Project name is required.");
  expect(
    apiErrorMessage({ detail: [{ msg: "Assertion failed, Root folder is invalid." }] }, "x"),
  ).toBe("Root folder is invalid.");
  expect(apiErrorMessage({ detail: [{ msg: "Field required" }] }, "x")).toBe("Field required");
  expect(apiErrorMessage(undefined, "Fallback")).toBe("Fallback");
  expect(apiErrorMessage({ detail: [] }, "Fallback")).toBe("Fallback");
  expect(apiErrorMessage("boom", "Fallback")).toBe("Fallback");
});

it("unwrap returns data or throws the API message", () => {
  expect(unwrap({ data: [1], error: undefined })).toEqual([1]);
  expect(() => unwrap({ data: undefined, error: { detail: "Project not found." } })).toThrow(
    "Project not found.",
  );
  expect(() => unwrap({ data: undefined, error: undefined }, "Nope")).toThrow("Nope");
});
