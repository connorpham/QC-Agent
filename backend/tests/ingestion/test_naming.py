from datetime import UTC, datetime

from app.ingestion.naming import (
    Frontmatter,
    markdown_path,
    normalized_path,
    original_path,
    render_markdown_file,
    split_frontmatter,
    stub_path,
    title_from_filename,
    title_slug,
)
from app.ingestion.taxonomy import default_templates_dir, load_taxonomy

TAXONOMY = load_taxonomy(default_templates_dir())
UPLOADED_AT = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


def _frontmatter(**overrides: object) -> Frontmatter:
    values: dict[str, object] = {
        "document_id": "01J9ABCDEF",
        "version": 3,
        "doc_type": "srs",
        "folder": "02-requirements",
        "title": "Cổng Khách hàng SRS",
        "kind": "converted",
        "source_file": "srs--cong-khach-hang-srs.docx",
        "source_sha256": "3f1c" * 16,
        "uploaded_by": "Nguyen Van A",
        "uploaded_at": UPLOADED_AT,
        "type_selected_by_user": "srs",
        "type_check": "match",
        "language": "vi",
        "visibility": "internal",
    }
    values.update(overrides)
    return Frontmatter(**values)  # type: ignore[arg-type]


def test_paths_follow_the_naming_convention() -> None:
    srs = TAXONOMY.resolve("srs")
    assert (
        original_path(srs, "customer-portal", "docx") == "02-requirements/srs--customer-portal.docx"
    )
    assert markdown_path(srs, "customer-portal") == "02-requirements/srs--customer-portal.md"
    assert (
        normalized_path(srs, "customer-portal")
        == "02-requirements/srs--customer-portal.normalized.md"
    )
    assert stub_path(srs) == "02-requirements/srs.md"
    adr = TAXONOMY.resolve("adr")
    assert original_path(adr, "use-postgres", "md") == "04-source/adr/adr--use-postgres.md"
    other = TAXONOMY.resolve("design/other")
    assert original_path(other, "notes", "pdf") == "03-design/other--notes.pdf"


def test_title_helpers() -> None:
    assert title_slug("Dự án Cổng Khách hàng") == "du-an-cong-khach-hang"
    assert title_from_filename("srs_customer-portal v2.docx") == "srs customer portal v2"
    assert title_from_filename("C:\\Users\\x\\Report.pdf") == "Report"
    assert title_from_filename(".docx") == "Untitled"


def test_frontmatter_round_trip() -> None:
    text = render_markdown_file(_frontmatter(), "# SRS\n\nBody text.\n\n")
    assert text.startswith("---\nqc_agent: 2\ndocument_id: 01J9ABCDEF\nversion: 3\n")
    assert text.endswith("---\n\n# SRS\n\nBody text.\n")
    data, body = split_frontmatter(text)
    assert data["title"] == "Cổng Khách hàng SRS"
    assert data["uploaded_by"] == "Nguyen Van A" and "@" not in text
    assert data["uploaded_at"] == "2026-10-01T09:30:00+00:00"
    assert data["normalized_approved_by"] is None
    assert list(data)[:3] == ["qc_agent", "document_id", "version"]
    assert body == "# SRS\n\nBody text.\n"


def test_stub_and_null_fields_render() -> None:
    text = render_markdown_file(
        _frontmatter(kind="stub", source_file=None, source_sha256=None, language=None), "x"
    )
    data, _ = split_frontmatter(text)
    assert data["kind"] == "stub" and data["source_file"] is None and data["language"] is None
