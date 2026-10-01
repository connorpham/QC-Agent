"""Deterministic conversion of uploaded files to Markdown (spec 6.3 step 2).

``convert_file`` is synchronous and CPU/IO bound; callers run it in a worker thread.
"""

from pathlib import Path

from app.ingestion.converters.base import (
    CSV_TRUNCATED,
    LOW_TEXT,
    ConversionError,
    ConversionMeta,
    ConversionResult,
    Converter,
)
from app.ingestion.converters.office import OfficeConverter
from app.ingestion.converters.pdf import PdfConverter
from app.ingestion.converters.text import CsvConverter, TextConverter

CONVERTERS: dict[str, Converter] = {
    "docx": OfficeConverter("docx"),
    "pptx": OfficeConverter("pptx"),
    "xlsx": OfficeConverter("xlsx"),
    "html": OfficeConverter("html"),
    "pdf": PdfConverter(),
    "md": TextConverter(),
    "txt": TextConverter(),
    "csv": CsvConverter(),
}

CONVERTIBLE_EXTENSIONS = frozenset(CONVERTERS)


def convert_file(path: Path, ext: str) -> ConversionResult:
    converter = CONVERTERS.get(ext)
    if converter is None:
        raise ConversionError(f"Files of type .{ext} cannot be converted.")
    return converter.convert(path)


__all__ = [
    "CONVERTERS",
    "CONVERTIBLE_EXTENSIONS",
    "CSV_TRUNCATED",
    "LOW_TEXT",
    "ConversionError",
    "ConversionMeta",
    "ConversionResult",
    "Converter",
    "convert_file",
]
