"""Per-project confirmation that converted document text may be sent to the Claude API
(spec 13 "Data processing"). Required before the first upload."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Project, User
from app.services import audit


class ConsentError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def has_consent(project: Project) -> bool:
    return bool(project.llm_consent)


async def record_consent(
    db: AsyncSession,
    project: Project,
    *,
    actor: User,
    confirmed_by_name: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if has_consent(project):
        raise ConsentError("LLM data processing is already confirmed for this project.")
    moment = now or datetime.now(UTC)
    consent = {
        "confirmed_by_name": confirmed_by_name.strip(),
        "confirmed_at": moment.isoformat(),
        "confirmed_by_user_id": str(actor.id),
    }
    project.llm_consent = consent
    await audit.record(
        db,
        "project.llm_consent",
        user_id=actor.id,
        project_id=project.id,
        target_type="project",
        target_id=str(project.id),
        details={"confirmed_by_name": consent["confirmed_by_name"]},
    )
    await db.commit()
    return consent
