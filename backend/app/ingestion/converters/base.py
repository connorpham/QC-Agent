"""Converter interface and shared helpers (spec 6.3 step 2)."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from langdetect import DetectorFactory, detect
from langdetect.lang_detect_exception import LangDetectException

DetectorFactory.seed = 0  # langdetect is otherwise non-deterministic for short texts

LOW_TEXT = "low_text"
CSV_TRUNCATED = "csv_truncated"
LOW_TEXT_CHARS_PER_PAGE = 200
OUTLINE_LIMIT = 30
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_LANGUAGE_SAMPLE_CHARS = 20_000
_LANGUAGE_MIN_CHARS = 20


class ConversionError(Exception):
    """Conversion failed; the message is shown to the uploader."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ConversionMeta:
    converter: str  # "<id>/<version>"
    chars: int
    pages: int | None = None
    outline: list[str] = field(default_factory=list)
    language: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "converter": self.converter,
            "chars": self.chars,
            "pages": self.pages,
            "outline": list(self.outline),
            "language": self.language,
        }


@dataclass(frozen=True)
class ConversionResult:
    markdown: str
    meta: ConversionMeta
    warnings: list[str] = field(default_factory=list)


class Converter(Protocol):
    id: str

    def convert(self, path: Path) -> ConversionResult: ...


def normalize_newlines(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\x0c", "\n")
    return text.strip("\n") + "\n" if text.strip() else ""


def extract_outline(markdown: str, limit: int = OUTLINE_LIMIT) -> list[str]:
    outline: list[str] = []
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            outline.append(f"{match.group(1)} {match.group(2)}")
            if len(outline) >= limit:
                break
    return outline


def detect_language(text: str) -> str | None:
    sample = text[:_LANGUAGE_SAMPLE_CHARS]
    if len(sample.strip()) < _LANGUAGE_MIN_CHARS:
        return None
    try:
        return str(detect(sample))
    except LangDetectException:
        return None


def build_result(
    markdown: str, *, converter: str, pages: int | None = None, warnings: list[str] | None = None
) -> ConversionResult:
    normalized = normalize_newlines(markdown)
    result_warnings = list(warnings or [])
    if (
        pages
        and len(normalized) / pages < LOW_TEXT_CHARS_PER_PAGE
        and LOW_TEXT not in result_warnings
    ):
        result_warnings.append(LOW_TEXT)
    meta = ConversionMeta(
        converter=converter,
        chars=len(normalized),
        pages=pages,
        outline=extract_outline(normalized),
        language=detect_language(normalized),
    )
    return ConversionResult(markdown=normalized, meta=meta, warnings=result_warnings)
