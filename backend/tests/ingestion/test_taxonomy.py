from pathlib import Path

import pytest

from app.ingestion.taxonomy import (
    TaxonomyError,
    UnknownDocType,
    default_templates_dir,
    load_taxonomy,
)

MINIMAL = """
version: 1
folders:
  - id: overview
    dir: 01-overview
    stage: Why
    doc_types:
      - {{ id: readme, title: Project README, required: true, template: readme.md{extra} }}
"""


def _write(tmp_path: Path, yaml_text: str, templates: tuple[str, ...] = ("readme.md",)) -> Path:
    (tmp_path / "doc-templates").mkdir()
    for name in templates:
        (tmp_path / "doc-templates" / name).write_text("# Template\n")
    (tmp_path / "taxonomy.yaml").write_text(yaml_text)
    return tmp_path


def test_default_taxonomy_matches_spec() -> None:
    taxonomy = load_taxonomy(default_templates_dir())
    assert taxonomy.version == 1
    assert [f.dir for f in taxonomy.folders] == [
        "01-overview",
        "02-requirements",
        "03-design",
        "04-source",
        "05-testing",
        "06-deployment",
    ]
    real_types = [t for t in taxonomy.doc_types if not t.is_other]
    assert len(real_types) == 20
    assert {t.key for t in taxonomy.required_types()} == {
        "readme",
        "project-charter",
        "brd",
        "srs",
        "architecture-c4",
        "repo-structure",
        "test-plan",
        "test-cases",
        "deploy-guide",
        "runbook",
    }
    adr = taxonomy.resolve("adr")
    assert adr.multi is True and adr.document_dir == "04-source/adr"
    assert taxonomy.resolve("api-spec").normalize is False
    assert taxonomy.resolve("srs").document_dir == "02-requirements"
    for doc_type in real_types:
        assert taxonomy.template_text(doc_type).startswith(f"# {doc_type.title}")


def test_every_folder_accepts_other() -> None:
    taxonomy = load_taxonomy(default_templates_dir())
    for folder in taxonomy.folders:
        other = taxonomy.resolve(f"{folder.id}/other")
        assert other.is_other and other.required is False and other.normalize is False
        assert other.folder_dir == folder.dir and other.template is None
    with pytest.raises(UnknownDocType):
        taxonomy.resolve("other")
    with pytest.raises(UnknownDocType):
        taxonomy.resolve("nonsense")


def test_minimal_file_loads(tmp_path: Path) -> None:
    taxonomy = load_taxonomy(_write(tmp_path, MINIMAL.format(extra="")))
    assert [t.key for t in taxonomy.doc_types] == ["readme", "overview/other"]


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        (MINIMAL.format(extra=", template: missing.md"), "does not exist"),
        (MINIMAL.format(extra=", multi: true"), "need a 'subdir'"),
        (MINIMAL.format(extra=", subdir: x"), "only allowed with multi"),
        (MINIMAL.format(extra=", colour: red"), "unknown doc_type keys"),
        (MINIMAL.format(extra="").replace("version: 1", "version: zero"), "positive integer"),
        (MINIMAL.format(extra="").replace("01-overview", "overview"), "02-requirements"),
    ],
)
def test_validation_errors(tmp_path: Path, yaml_text: str, message: str) -> None:
    with pytest.raises(TaxonomyError, match=message):
        load_taxonomy(_write(tmp_path, yaml_text))


def test_duplicate_doc_type_id_is_rejected(tmp_path: Path) -> None:
    duplicated = MINIMAL.format(extra="") + (
        "  - id: requirements\n    dir: 02-requirements\n    stage: What\n    doc_types:\n"
        "      - { id: readme, title: Again, template: readme.md }\n"
    )
    with pytest.raises(TaxonomyError, match="defined twice"):
        load_taxonomy(_write(tmp_path, duplicated))


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(TaxonomyError, match="not found"):
        load_taxonomy(tmp_path)
