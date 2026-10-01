"""Project workspace in storage: the six folders, ``project.yaml``, stubs for required types and
the gap report (spec 5.1, 5.5). ``ensure_workspace`` is idempotent: it runs at project creation
and again from the first publish of a project that predates provisioning."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Document, DocumentVersion, Project, User
from app.ingestion.gaps import (
    DocumentFact,
    GapReport,
    build_gap_report,
    render_gap_report_markdown,
)
from app.ingestion.naming import Frontmatter, stub_path
from app.ingestion.stubs import render_stub
from app.ingestion.taxonomy import DocType, Taxonomy
from app.storage.base import StorageBackend

PROJECT_YAML = "project.yaml"
REPORTS_DIR = "_reports"
GAP_REPORT_MD = f"{REPORTS_DIR}/gap-report.md"
GAP_REPORT_JSON = f"{REPORTS_DIR}/gap-report.json"
PROVISIONED_AT = "provisioned_at"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def document_facts(db: AsyncSession, project_id: uuid.UUID) -> list[DocumentFact]:
    rows = (
        await db.execute(
            select(Document.doc_type, Document.is_stub).where(Document.project_id == project_id)
        )
    ).all()
    return [DocumentFact(doc_type=doc_type, is_stub=is_stub) for doc_type, is_stub in rows]


def render_project_yaml(project: Project, taxonomy: Taxonomy, report: GapReport) -> str:
    data: dict[str, Any] = {
        "qc_agent": 2,
        "project": {
            "id": str(project.id),
            "slug": project.slug,
            "name": project.name,
            "client_name": project.client_name,
        },
        "taxonomy_version": taxonomy.version,
        "folders": [folder.dir for folder in taxonomy.folders],
        "documents": sum(e.documents for f in report.folders for e in f.entries),
        "required_present": report.required_present,
        "required_total": report.required_total,
        "updated_at": report.generated_at.isoformat(),
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


async def refresh_reports(
    db: AsyncSession,
    *,
    project: Project,
    backend: StorageBackend,
    taxonomy: Taxonomy,
    now: datetime,
) -> GapReport:
    report = build_gap_report(
        taxonomy,
        await document_facts(db, project.id),
        project_slug=project.slug,
        project_name=project.name,
        generated_at=now,
    )
    await backend.put_file(
        GAP_REPORT_MD, render_gap_report_markdown(report).encode("utf-8"), "text/markdown"
    )
    await backend.put_file(
        GAP_REPORT_JSON,
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False).encode("utf-8"),
        "application/json",
    )
    await backend.put_file(
        PROJECT_YAML, render_project_yaml(project, taxonomy, report).encode("utf-8"), "text/yaml"
    )
    return report


def stub_frontmatter(
    document: Document, doc_type: DocType, actor: User, now: datetime
) -> Frontmatter:
    return Frontmatter(
        document_id=str(document.id),
        version=1,
        doc_type=doc_type.id,
        folder=doc_type.folder_dir,
        title=doc_type.title,
        kind="stub",
        source_file=None,
        source_sha256=None,
        uploaded_by=actor.display_name,
        uploaded_at=now,
        type_selected_by_user=doc_type.key,
        type_check="skipped",
        language="en",
        visibility="internal",
    )


async def create_stub(
    db: AsyncSession,
    *,
    project: Project,
    doc_type: DocType,
    taxonomy: Taxonomy,
    backend: StorageBackend,
    actor: User,
    now: datetime,
) -> Document:
    document = Document(
        project_id=project.id,
        folder_id=doc_type.folder_id,
        doc_type=doc_type.key,
        title=doc_type.title,
        slug="",
        visibility="internal",
        current_version=1,
        is_stub=True,
        created_by=actor.id,
    )
    db.add(document)
    await db.flush()
    text = render_stub(
        doc_type, taxonomy.template_text(doc_type), stub_frontmatter(document, doc_type, actor, now)
    )
    data = text.encode("utf-8")
    stored = await backend.put_file(stub_path(doc_type), data, "text/markdown")
    db.add(
        DocumentVersion(
            document_id=document.id,
            version=1,
            sha256=sha256_hex(data),
            original_path=None,
            original_storage_version=None,
            markdown_path=stub_path(doc_type),
            markdown_storage_version=stored.version_id,
            markdown_text=text,
            uploaded_by=actor.id,
            upload_item_id=None,
        )
    )
    return document


async def ensure_workspace(
    db: AsyncSession,
    *,
    project: Project,
    backend: StorageBackend,
    taxonomy: Taxonomy,
    actor: User,
    now: datetime | None = None,
) -> None:
    """Create folders, stubs for required types without any document, repair stub files that
    disappeared from storage, then write the reports. Safe to call repeatedly."""
    moment = now or datetime.now(UTC)
    for folder in taxonomy.folders:
        await backend.ensure_folder(folder.dir)
        for doc_type in folder.doc_types:
            if doc_type.multi:
                await backend.ensure_folder(doc_type.document_dir)
    await backend.ensure_folder(REPORTS_DIR)
    typed = set(
        (await db.scalars(select(Document.doc_type).where(Document.project_id == project.id))).all()
    )
    for doc_type in taxonomy.required_types():
        if doc_type.key not in typed:
            await create_stub(
                db,
                project=project,
                doc_type=doc_type,
                taxonomy=taxonomy,
                backend=backend,
                actor=actor,
                now=moment,
            )
    stubs = (
        await db.execute(
            select(Document, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.document_id == Document.id)
            .where(Document.project_id == project.id, Document.is_stub.is_(True))
        )
    ).all()
    for _document, version in stubs:
        if not await backend.exists(version.markdown_path):
            stored = await backend.put_file(
                version.markdown_path, version.markdown_text.encode("utf-8"), "text/markdown"
            )
            version.markdown_storage_version = stored.version_id
    await refresh_reports(db, project=project, backend=backend, taxonomy=taxonomy, now=moment)
    project.storage = {**project.storage, PROVISIONED_AT: moment.isoformat()}


def is_provisioned(project: Project) -> bool:
    return PROVISIONED_AT in project.storage
