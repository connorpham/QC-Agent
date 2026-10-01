"""Stub documents for missing required types (spec 5.5)."""

from app.ingestion.naming import Frontmatter, render_markdown_file
from app.ingestion.taxonomy import DocType

STUB_NOTICE = (
    "> Placeholder: no {title} has been uploaded for this project yet. "
    "Upload one and this stub is replaced."
)


def render_stub(doc_type: DocType, template_text: str, fm: Frontmatter) -> str:
    body = STUB_NOTICE.format(title=doc_type.title) + "\n\n" + template_text.strip("\n")
    return render_markdown_file(fm, body)
