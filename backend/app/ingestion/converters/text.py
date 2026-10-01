"""Built-in converters for Markdown, plain text and CSV."""

import csv
import io
from pathlib import Path

from app.ingestion.converters.base import (
    CSV_TRUNCATED,
    ConversionError,
    ConversionResult,
    build_result,
)

CSV_ROW_LIMIT = 500
_BUILTIN_TEXT = "builtin-text/1"
_BUILTIN_CSV = "builtin-csv/1"


def decode_utf8(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConversionError("Text files must be UTF-8 encoded.") from exc


class TextConverter:
    """md and txt: UTF-8 normalised, LF line endings, content otherwise untouched."""

    id = "text"

    def convert(self, path: Path) -> ConversionResult:
        return build_result(decode_utf8(path), converter=_BUILTIN_TEXT)


def _cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


class CsvConverter:
    """csv: a Markdown table capped at CSV_ROW_LIMIT data rows."""

    id = "csv"

    def convert(self, path: Path) -> ConversionResult:
        text = decode_utf8(path)
        try:
            rows = list(csv.reader(io.StringIO(text)))
        except csv.Error as exc:  # the message may quote content: report the class only
            raise ConversionError(f"CSV file could not be parsed: {type(exc).__name__}") from exc
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        if not rows:
            raise ConversionError("CSV file has no rows.")
        header, data = rows[0], rows[1:]
        width = max(len(row) for row in rows)
        header = header + [""] * (width - len(header))
        lines = [
            "| " + " | ".join(_cell(c) for c in header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in data[:CSV_ROW_LIMIT]:
            padded = row + [""] * (width - len(row))
            lines.append("| " + " | ".join(_cell(c) for c in padded) + " |")
        warnings: list[str] = []
        if len(data) > CSV_ROW_LIMIT:
            warnings.append(CSV_TRUNCATED)
            lines += ["", f"> Truncated: showing {CSV_ROW_LIMIT} of {len(data)} rows."]
        return build_result("\n".join(lines), converter=_BUILTIN_CSV, warnings=warnings)
