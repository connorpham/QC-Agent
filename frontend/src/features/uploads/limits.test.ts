import { expect, it } from "vitest";
import { batchGuard, extensionOf, guardFile } from "./limits";

const limits = {
  max_file_mb: 50,
  max_batch_mb: 500,
  allowed_extensions: ["csv", "docx", "html", "md", "pdf", "pptx", "txt", "xlsx", "zip"],
  zip_max_entries: 200,
};

function file(name: string, bytes: number): File {
  return new File([new Uint8Array(bytes)], name);
}

it("normalises extensions (case, htm alias, no extension)", () => {
  expect(extensionOf("Report.DOCX")).toBe("docx");
  expect(extensionOf("page.htm")).toBe("html");
  expect(extensionOf("archive.tar.gz")).toBe("gz");
  expect(extensionOf("README")).toBeNull();
});

it("refuses unsupported extensions and oversized files before upload", () => {
  expect(guardFile(file("virus.exe", 10), limits)).toBe(
    "File type is not supported. Allowed: csv, docx, html, md, pdf, pptx, txt, xlsx, zip.",
  );
  expect(guardFile(file("README", 10), limits)).toMatch(/not supported/);
  expect(guardFile(file("big.pdf", 50 * 1024 * 1024 + 1), limits)).toBe(
    "File is larger than 50 MB.",
  );
  expect(guardFile(file("ok.pdf", 50 * 1024 * 1024), limits)).toBeNull();
  expect(guardFile(file("page.HTM", 10), limits)).toBeNull();
});

it("refuses a batch over the total limit", () => {
  const half = 250 * 1024 * 1024;
  expect(batchGuard([file("a.pdf", half), file("b.pdf", half)], limits)).toBeNull();
  expect(batchGuard([file("a.pdf", half), file("b.pdf", half + 1)], limits)).toBe(
    "The selected files exceed 500 MB in total. Remove some files or upload in several batches.",
  );
});
