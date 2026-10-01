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
OLE_MAGIC = bytes.fromhex("D0CF11E0A1B11AE1")  # Compound File Binary: encrypted OOXML, .doc, ...
PROTECTED_OR_LEGACY = (
    "Document is password-protected or in a legacy format; save it as a regular "
    ".docx/.xlsx/.pptx and upload again."
)
MAX_ARCHIVE_ENTRIES = 10_000
MAX_UNPACKED_BYTES = 256 * 1024 * 1024
UNPACK_RATIO = 50  # declared uncompressed bytes allowed per byte of the file
_engine: MarkItDown | None = None


def markitdown_engine() -> MarkItDown:
    global _engine
    if _engine is None:
        _engine = MarkItDown(enable_plugins=False)
    return _engine


def markitdown_version() -> str:
    return f"markitdown/{version('markitdown')}"


def check_container(path: Path, ext: str) -> None:
    """Reject files whose bytes do not match their extension, OLE containers (encrypted OOXML or
    legacy binary formats) and OOXML archives too large to unpack safely."""
    if ext in OOXML_EXTENSIONS:
        with path.open("rb") as handle:
            if handle.read(len(OLE_MAGIC)) == OLE_MAGIC:
                raise ConversionError(PROTECTED_OR_LEGACY)
        if not zipfile.is_zipfile(path):
            raise ConversionError("File content does not match its extension.")
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if "[Content_Types].xml" not in archive.namelist():
                raise ConversionError("File content does not match its extension.")
            # Declared sizes are attacker-controlled, but they are what the OOXML readers trust
            # when they inflate the parts, so they are bounded before conversion.
            cap = min(MAX_UNPACKED_BYTES, UNPACK_RATIO * path.stat().st_size)
            if len(infos) > MAX_ARCHIVE_ENTRIES or sum(i.file_size for i in infos) > cap:
                raise ConversionError("Document archive is too large to process.")
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
