"""File names and Markdown frontmatter for the knowledge base (spec 5.3)."""

import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any

import yaml

from app.core.slugs import slugify
from app.ingestion.taxonomy import DocType

QC_AGENT_FORMAT = 2
MARKDOWN_EXT = "md"
NORMALIZED_SUFFIX = ".normalized.md"  # reserved for the agent plan
_SEPARATORS = re.compile(r"[_\-\s]+")


def title_slug(title: str) -> str:
    return slugify(title, max_len=80)


def title_from_filename(name: str) -> str:
    """Default document title: the file stem with separators turned into spaces."""
    base = PurePosixPath(name.replace("\\", "/")).name
    stem, dot, _ext = base.rpartition(".")
    cleaned = _SEPARATORS.sub(" ", stem if dot else base).strip()
    return cleaned[:200] or "Untitled"


def original_path(doc_type: DocType, slug: str, ext: str) -> str:
    return f"{doc_type.document_dir}/{doc_type.id}--{slug}.{ext}"


def markdown_path(doc_type: DocType, slug: str) -> str:
    return f"{doc_type.document_dir}/{doc_type.id}--{slug}.{MARKDOWN_EXT}"


def normalized_path(doc_type: DocType, slug: str) -> str:
    return f"{doc_type.document_dir}/{doc_type.id}--{slug}{NORMALIZED_SUFFIX}"


def stub_path(doc_type: DocType) -> str:
    return f"{doc_type.folder_dir}/{doc_type.id}.{MARKDOWN_EXT}"


@dataclass(frozen=True)
class Frontmatter:
    document_id: str
    version: int
    doc_type: str
    folder: str
    title: str
    kind: str  # converted | normalized | stub
    source_file: str | None
    source_sha256: str | None
    uploaded_by: str  # display name only, never an e-mail
    uploaded_at: datetime
    type_selected_by_user: str
    type_check: str  # match | mismatch_kept | mismatch_changed | skipped
    language: str | None
    visibility: str  # internal | shared


def render_frontmatter(fm: Frontmatter) -> str:
    data: dict[str, Any] = {"qc_agent": QC_AGENT_FORMAT}
    for key, value in asdict(fm).items():
        data[key] = value.isoformat() if isinstance(value, datetime) else value
    data["normalized_approved_by"] = None
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


def render_markdown_file(fm: Frontmatter, body: str) -> str:
    return render_frontmatter(fm) + "\n" + body.strip("\n") + "\n"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter mapping, body). Raises ValueError when there is no frontmatter."""
    if not text.startswith("---\n"):
        raise ValueError("Markdown file has no frontmatter.")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Frontmatter is not terminated.")
    data = yaml.safe_load(text[4:end])
    if not isinstance(data, dict):
        raise ValueError("Frontmatter is not a mapping.")
    return data, text[end + 5 :].lstrip("\n")
