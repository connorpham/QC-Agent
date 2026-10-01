"""markitdown-based conversion for docx, pptx, xlsx and html.

Verified against markitdown 0.1.8: ``MarkItDown().convert(path, stream_info=StreamInfo(...))``
returns ``DocumentConverterResult`` whose ``text_content`` equals ``markdown``. markitdown
sniffs content and silently converts unrecognised bytes as plain text (and extracts plain zip
archives), so OOXML containers are validated here before conversion.
"""

import zipfile
from importlib.metadata import version
from pathlib import Path

from markitdown import MarkItDown, MarkItDownException, StreamInfo

from app.ingestion.converters.base import ConversionError, ConversionResult, build_result

OOXML_EXTENSIONS = frozenset({"docx", "pptx", "xlsx"})
_engine: MarkItDown | None = None


def markitdown_engine() -> MarkItDown:
    global _engine
    if _engine is None:
        _engine = MarkItDown(enable_plugins=False)
    return _engine


def markitdown_version() -> str:
    return f"markitdown/{version('markitdown')}"


def check_container(path: Path, ext: str) -> None:
    """Reject files whose bytes do not match their extension."""
    if ext in OOXML_EXTENSIONS:
        if not zipfile.is_zipfile(path):
            raise ConversionError("File content does not match its extension.")
        with zipfile.ZipFile(path) as archive:
            if "[Content_Types].xml" not in archive.namelist():
                raise ConversionError("File content does not match its extension.")
    elif ext == "pdf":
        with path.open("rb") as handle:
            if not handle.read(5).startswith(b"%PDF-"):
                raise ConversionError("File content does not match its extension.")


def markitdown_text(path: Path, ext: str) -> str:
    try:
        result = markitdown_engine().convert(str(path), stream_info=StreamInfo(extension=f".{ext}"))
    except MarkItDownException as exc:
        raise ConversionError(f"The file could not be converted ({type(exc).__name__}).") from exc
    return str(result.text_content)


class OfficeConverter:
    """docx, pptx, xlsx and html via markitdown."""

    id = "markitdown"

    def __init__(self, ext: str) -> None:
        self._ext = ext

    def convert(self, path: Path) -> ConversionResult:
        check_container(path, self._ext)
        return build_result(markitdown_text(path, self._ext), converter=markitdown_version())
