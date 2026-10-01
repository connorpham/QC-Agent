"""Gap report: per folder, each document type is present, stub or missing (spec 5.5)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.ingestion.taxonomy import Taxonomy

PRESENT = "present"
STUB = "stub"
MISSING = "missing"


@dataclass(frozen=True)
class DocumentFact:
    """The two facts about a document the report needs; decoupled from the ORM."""

    doc_type: str  # taxonomy key
    is_stub: bool


@dataclass(frozen=True)
class GapEntry:
    doc_type: str
    title: str
    required: bool
    status: str
    documents: int


@dataclass(frozen=True)
class GapFolder:
    id: str
    dir: str
    stage: str
    entries: tuple[GapEntry, ...]


@dataclass(frozen=True)
class GapReport:
    project_slug: str
    project_name: str
    generated_at: datetime
    folders: tuple[GapFolder, ...]

    @property
    def required_total(self) -> int:
        return sum(1 for f in self.folders for e in f.entries if e.required)

    @property
    def required_present(self) -> int:
        return sum(1 for f in self.folders for e in f.entries if e.required and e.status == PRESENT)

    @property
    def completeness(self) -> float:
        return 1.0 if self.required_total == 0 else self.required_present / self.required_total

    def to_dict(self) -> dict[str, Any]:
        return {
            "qc_agent": 2,
            "project": {"slug": self.project_slug, "name": self.project_name},
            "generated_at": self.generated_at.isoformat(),
            "required_total": self.required_total,
            "required_present": self.required_present,
            "completeness": round(self.completeness, 4),
            "folders": [
                {
                    "id": f.id,
                    "dir": f.dir,
                    "stage": f.stage,
                    "doc_types": [
                        {
                            "doc_type": e.doc_type,
                            "title": e.title,
                            "required": e.required,
                            "status": e.status,
                            "documents": e.documents,
                        }
                        for e in f.entries
                    ],
                }
                for f in self.folders
            ],
        }


def build_gap_report(
    taxonomy: Taxonomy,
    facts: Iterable[DocumentFact],
    *,
    project_slug: str,
    project_name: str,
    generated_at: datetime,
) -> GapReport:
    real: dict[str, int] = {}
    stubs: set[str] = set()
    for fact in facts:
        if fact.is_stub:
            stubs.add(fact.doc_type)
        else:
            real[fact.doc_type] = real.get(fact.doc_type, 0) + 1
    folders: list[GapFolder] = []
    for folder in taxonomy.folders:
        entries: list[GapEntry] = []
        for doc_type in folder.doc_types:
            if doc_type.is_other:
                continue
            count = real.get(doc_type.key, 0)
            if count:
                status = PRESENT
            elif doc_type.key in stubs:
                status = STUB
            else:
                status = MISSING
            entries.append(
                GapEntry(
                    doc_type=doc_type.key,
                    title=doc_type.title,
                    required=doc_type.required,
                    status=status,
                    documents=count,
                )
            )
        folders.append(
            GapFolder(id=folder.id, dir=folder.dir, stage=folder.stage, entries=tuple(entries))
        )
    return GapReport(
        project_slug=project_slug,
        project_name=project_name,
        generated_at=generated_at,
        folders=tuple(folders),
    )


def render_gap_report_markdown(report: GapReport) -> str:
    lines = [
        f"# Gap report: {report.project_name}",
        "",
        f"Generated {report.generated_at.isoformat()} by QC-Agent.",
        "",
        f"Required document types present: {report.required_present} of "
        f"{report.required_total} ({report.completeness:.0%}).",
        "",
    ]
    for folder in report.folders:
        lines += [
            f"## {folder.dir} ({folder.stage})",
            "",
            "| Document type | Required | Status | Documents |",
            "| --- | --- | --- | --- |",
        ]
        for entry in folder.entries:
            required = "yes" if entry.required else "no"
            lines.append(f"| {entry.title} | {required} | {entry.status} | {entry.documents} |")
        lines.append("")
    return "\n".join(lines)
