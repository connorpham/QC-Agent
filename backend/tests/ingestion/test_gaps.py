import json
from datetime import UTC, datetime

from app.ingestion.gaps import (
    MISSING,
    PRESENT,
    STUB,
    DocumentFact,
    build_gap_report,
    render_gap_report_markdown,
)
from app.ingestion.naming import Frontmatter, split_frontmatter
from app.ingestion.stubs import render_stub
from app.ingestion.taxonomy import default_templates_dir, load_taxonomy

TAXONOMY = load_taxonomy(default_templates_dir())
NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _report(facts: list[DocumentFact]):  # type: ignore[no-untyped-def]
    return build_gap_report(
        TAXONOMY, facts, project_slug="demo", project_name="Demo", generated_at=NOW
    )


def test_statuses_and_completeness() -> None:
    report = _report(
        [
            DocumentFact("srs", False),
            DocumentFact("srs", False),
            DocumentFact("readme", True),
            DocumentFact("requirements/other", False),
        ]
    )
    by_type = {e.doc_type: e for f in report.folders for e in f.entries}
    assert by_type["srs"].status == PRESENT and by_type["srs"].documents == 2
    assert by_type["readme"].status == STUB
    assert by_type["brd"].status == MISSING
    assert "requirements/other" not in by_type
    assert report.required_total == 10 and report.required_present == 1
    assert report.completeness == 0.1


def test_empty_project_has_zero_completeness_and_json_shape() -> None:
    report = _report([])
    data = json.loads(json.dumps(report.to_dict()))
    assert data["completeness"] == 0 and data["required_total"] == 10
    assert [f["dir"] for f in data["folders"]][0] == "01-overview"
    assert data["folders"][0]["doc_types"][0] == {
        "doc_type": "readme",
        "title": "Project README",
        "required": True,
        "status": "missing",
        "documents": 0,
    }


def test_markdown_rendering() -> None:
    text = render_gap_report_markdown(_report([DocumentFact("runbook", False)]))
    assert text.startswith("# Gap report: Demo\n")
    assert "Required document types present: 1 of 10 (10%)." in text
    assert "| Runbook | yes | present | 1 |" in text
    assert "| Release Notes | no | missing | 0 |" in text


def test_stub_rendering_uses_template_and_notice() -> None:
    srs = TAXONOMY.resolve("srs")
    fm = Frontmatter(
        document_id="doc",
        version=1,
        doc_type="srs",
        folder="02-requirements",
        title="Software Requirements Specification",
        kind="stub",
        source_file=None,
        source_sha256=None,
        uploaded_by="Owner",
        uploaded_at=NOW,
        type_selected_by_user="srs",
        type_check="skipped",
        language="en",
        visibility="internal",
    )
    text = render_stub(srs, TAXONOMY.template_text(srs), fm)
    data, body = split_frontmatter(text)
    assert data["kind"] == "stub"
    assert body.startswith(
        "> Placeholder: no Software Requirements Specification has been uploaded"
    )
    assert "# Software Requirements Specification" in body and "## Functional requirements" in body
