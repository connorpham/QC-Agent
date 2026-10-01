"""PDF conversion: markitdown text with a pymupdf fallback; pymupdf provides the page count
and detects password protection (spec 6.3 step 2, 14)."""

from pathlib import Path

import pymupdf

from app.ingestion.converters.base import ConversionError, ConversionResult, build_result
from app.ingestion.converters.office import check_container, markitdown_text, markitdown_version


def pymupdf_version() -> str:
    return f"pymupdf/{pymupdf.VersionBind}"


class PdfConverter:
    id = "pdf"

    def convert(self, path: Path) -> ConversionResult:
        check_container(path, "pdf")
        try:
            document = pymupdf.open(str(path))
        except (pymupdf.FileDataError, pymupdf.EmptyFileError, RuntimeError) as exc:
            raise ConversionError("File is not a readable PDF.") from exc
        with document:
            if document.needs_pass:
                raise ConversionError(
                    "PDF is password-protected. Remove the password and upload again."
                )
            pages = int(document.page_count)
            fallback = "\n\n".join(
                str(document.load_page(index).get_text("text")) for index in range(pages)
            )
        try:
            markdown = markitdown_text(path, "pdf")
            converter = markitdown_version()
        except ConversionError:
            markdown = ""
            converter = pymupdf_version()
        if not markdown.strip():
            markdown = fallback
            converter = pymupdf_version()
        return build_result(markdown, converter=converter, pages=pages)
