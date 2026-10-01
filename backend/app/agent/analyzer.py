"""Analyzer interface (spec 7.1, check only). The agent plan adds the SDK implementation and
``normalize``; this plan ships ``SkipAnalyzer`` for production and ``FakeAnalyzer`` for tests."""

import uuid
from dataclasses import dataclass, field
from typing import Literal, Protocol

Verdict = Literal["match", "mismatch", "skipped"]
SKIP_EXPLANATION = "Type check is not available yet; the selected type was kept."


@dataclass(frozen=True)
class ExistingDocument:
    document_id: uuid.UUID
    doc_type: str
    title: str


@dataclass(frozen=True)
class CheckItem:
    item_id: uuid.UUID
    file_name: str
    selected_doc_type: str
    title: str
    outline: list[str]
    preview: str
    language: str | None


@dataclass(frozen=True)
class CheckBatch:
    project_id: uuid.UUID
    items: list[CheckItem]
    allowed_doc_types: list[str]
    existing_documents: list[ExistingDocument] = field(default_factory=list)


@dataclass(frozen=True)
class ItemVerdict:
    item_id: uuid.UUID
    verdict: Verdict
    explanation: str = ""
    suggested_doc_type: str | None = None
    version_of_document_id: uuid.UUID | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class CheckResult:
    verdicts: list[ItemVerdict]
    cost_usd: float = 0.0


class Analyzer(Protocol):
    async def check(self, batch: CheckBatch) -> CheckResult: ...


class SkipAnalyzer:
    """Production default until the agent plan: every item is ``skipped``."""

    async def check(self, batch: CheckBatch) -> CheckResult:
        return CheckResult(
            verdicts=[
                ItemVerdict(item_id=item.item_id, verdict="skipped", explanation=SKIP_EXPLANATION)
                for item in batch.items
            ]
        )
