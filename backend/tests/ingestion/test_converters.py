from pathlib import Path

import pytest

from app.ingestion.converters import (
    CSV_TRUNCATED,
    LOW_TEXT,
    ConversionError,
    convert_file,
)
from tests.helpers.files import make_docx, make_pdf, make_pptx, make_xlsx

VI_TEXT = (
    "Hệ thống cho phép người dùng đăng nhập bằng mật khẩu và mã xác thực hai lớp. "
    "Tài liệu này mô tả yêu cầu phần mềm cho cổng khách hàng."
)
EN_TEXT = (
    "The system shall allow users to log in with a password and a one-time code. "
    "This document describes the software requirements for the customer portal."
)


def test_docx_headings_outline_and_language(tmp_path: Path) -> None:
    path = make_docx(
        tmp_path / "srs.docx",
        headings=[(1, "Software Requirements"), (2, "Scope")],
        paragraphs=[VI_TEXT, VI_TEXT],
    )
    result = convert_file(path, "docx")
    assert result.markdown.startswith("# Software Requirements\n")
    assert result.meta.outline == ["# Software Requirements", "## Scope"]
    assert result.meta.language == "vi"
    assert result.meta.converter.startswith("markitdown/")
    assert result.meta.pages is None and result.meta.chars == len(result.markdown)
    assert result.warnings == []


def test_pptx_and_xlsx(tmp_path: Path) -> None:
    pptx = convert_file(make_pptx(tmp_path / "plan.pptx", [("Test Plan", EN_TEXT)]), "pptx")
    assert "# Test Plan" in pptx.markdown and pptx.meta.language == "en"
    xlsx = convert_file(
        make_xlsx(tmp_path / "cases.xlsx", "Cases", [["ID", "Title"], ["TC-1", "Login works"]]),
        "xlsx",
    )
    assert "## Cases" in xlsx.markdown and "| TC-1 | Login works |" in xlsx.markdown


def test_html(tmp_path: Path) -> None:
    path = tmp_path / "runbook.html"
    path.write_text(f"<html><body><h1>Runbook</h1><p>{EN_TEXT}</p><h2>Steps</h2></body></html>")
    result = convert_file(path, "html")
    assert result.meta.outline == ["# Runbook", "## Steps"]


def test_pdf_pages_and_text(tmp_path: Path) -> None:
    page = "\n".join([EN_TEXT] * 3)  # about 450 characters per page, above the low-text bar
    path = make_pdf(tmp_path / "guide.pdf", [page, page, page])
    result = convert_file(path, "pdf")
    assert result.meta.pages == 3
    assert "customer portal" in result.markdown
    assert "\x0c" not in result.markdown
    assert result.warnings == []


def test_blank_pdf_gets_low_text_warning_and_pymupdf_fallback(tmp_path: Path) -> None:
    result = convert_file(make_pdf(tmp_path / "scan.pdf", ["", "", ""]), "pdf")
    assert result.meta.pages == 3
    assert LOW_TEXT in result.warnings
    assert result.meta.converter.startswith("pymupdf/")
    assert result.meta.language is None


def test_password_protected_pdf_is_rejected_with_a_clear_reason(tmp_path: Path) -> None:
    path = make_pdf(tmp_path / "secret.pdf", [EN_TEXT], password="pw")
    with pytest.raises(ConversionError, match="password-protected"):
        convert_file(path, "pdf")


@pytest.mark.parametrize("ext", ["docx", "pptx", "xlsx", "pdf"])
def test_mismatched_content_is_rejected(tmp_path: Path, ext: str) -> None:
    path = tmp_path / f"fake.{ext}"
    path.write_bytes(b"this is plain text pretending to be a document")
    with pytest.raises(ConversionError, match="does not match"):
        convert_file(path, ext)


def test_zip_disguised_as_docx_is_rejected(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "fake.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(ConversionError, match="does not match"):
        convert_file(path, "docx")


def test_markdown_and_text_pass_through_with_normalised_newlines(tmp_path: Path) -> None:
    path = tmp_path / "notes.md"
    path.write_bytes(b"\xef\xbb\xbf# Notes\r\n\r\nLine one\r\nLine two")
    result = convert_file(path, "md")
    assert result.markdown == "# Notes\n\nLine one\nLine two\n"
    assert result.meta.converter == "builtin-text/1"
    txt = tmp_path / "plain.txt"
    txt.write_bytes("Ghi chú\n".encode())
    assert convert_file(txt, "txt").markdown == "Ghi chú\n"


def test_non_utf8_text_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"caf\xe9")
    with pytest.raises(ConversionError, match="UTF-8"):
        convert_file(path, "txt")


def test_csv_becomes_table_and_is_capped(tmp_path: Path) -> None:
    path = tmp_path / "cases.csv"
    rows = ["id,title,expected"] + [f"TC-{i},Case {i}|x,ok" for i in range(600)]
    path.write_text("\n".join(rows))
    result = convert_file(path, "csv")
    assert result.markdown.startswith("| id | title | expected |\n| --- | --- | --- |\n")
    assert "| TC-0 | Case 0\\|x | ok |" in result.markdown
    assert "TC-500" not in result.markdown
    assert CSV_TRUNCATED in result.warnings
    assert result.markdown.rstrip().endswith("> Truncated: showing 500 of 600 rows.")


def test_unknown_extension(tmp_path: Path) -> None:
    with pytest.raises(ConversionError, match="cannot be converted"):
        convert_file(tmp_path / "x.exe", "exe")


def _inflate_declared_size(path: Path, entry: bytes, declared: int) -> None:
    """Rewrite one entry's declared uncompressed size in the central directory (a zip bomb
    announces its size there; the bytes themselves stay small)."""
    import struct

    data = bytearray(path.read_bytes())
    offset = 0
    while (offset := data.find(b"PK\x01\x02", offset)) != -1:
        name_len = struct.unpack_from("<H", data, offset + 28)[0]
        if bytes(data[offset + 46 : offset + 46 + name_len]) == entry:
            struct.pack_into("<I", data, offset + 24, declared)
            path.write_bytes(bytes(data))
            return
        offset += 4
    raise AssertionError(f"central directory entry for {entry!r} not found")


def test_docx_with_oversized_declared_contents_is_rejected(tmp_path: Path) -> None:
    path = make_docx(tmp_path / "bomb.docx", headings=[(1, "Title")], paragraphs=[EN_TEXT])
    _inflate_declared_size(path, b"word/document.xml", 300 * 1024 * 1024)
    with pytest.raises(ConversionError, match="^Document archive is too large to process.$"):
        convert_file(path, "docx")


def test_docx_with_too_many_entries_is_rejected(tmp_path: Path) -> None:
    import zipfile

    path = tmp_path / "many.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        for i in range(10_000):
            archive.writestr(f"p/{i}.xml", "")
    with pytest.raises(ConversionError, match="^Document archive is too large to process.$"):
        convert_file(path, "docx")


@pytest.mark.parametrize("ext", ["docx", "xlsx", "pptx"])
def test_ole_container_is_rejected_as_protected_or_legacy(tmp_path: Path, ext: str) -> None:
    path = tmp_path / f"locked.{ext}"
    path.write_bytes(bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 512)
    with pytest.raises(ConversionError) as excinfo:
        convert_file(path, ext)
    assert excinfo.value.message == (
        "Document is password-protected or in a legacy format; save it as a regular "
        ".docx/.xlsx/.pptx and upload again."
    )


def test_csv_parse_error_is_a_conversion_error_without_content(tmp_path: Path) -> None:
    import csv

    path = tmp_path / "huge.csv"
    path.write_text("id,notes\n1," + "S" * (csv.field_size_limit() + 1) + "\n", encoding="utf-8")
    with pytest.raises(ConversionError) as excinfo:
        convert_file(path, "csv")
    assert excinfo.value.message == "CSV file could not be parsed: Error"
