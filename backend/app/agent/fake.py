"""Scripted analyzer for tests: verdicts keyed by file name, batches recorded."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from app.agent.analyzer import CheckBatch, CheckResult, ItemVerdict, Verdict


@dataclass(frozen=True)
class ScriptedVerdict:
    verdict: Verdict
    explanation: str = ""
    suggested_doc_type: str | None = None
    version_of_document_id: uuid.UUID | None = None
    confidence: float | None = 0.9


class FakeAnalyzer:
    def __init__(
        self,
        scripted: Mapping[str, ScriptedVerdict] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.scripted = dict(scripted or {})
        self.error = error
        self.batches: list[CheckBatch] = []

    async def check(self, batch: CheckBatch) -> CheckResult:
        self.batches.append(batch)
        if self.error is not None:
            raise self.error
        verdicts = []
        for item in batch.items:
            script = self.scripted.get(item.file_name, ScriptedVerdict("match", "Content matches."))
            verdicts.append(
                ItemVerdict(
                    item_id=item.item_id,
                    verdict=script.verdict,
                    explanation=script.explanation,
                    suggested_doc_type=script.suggested_doc_type,
                    version_of_document_id=script.version_of_document_id,
                    confidence=script.confidence,
                )
            )
        return CheckResult(verdicts=verdicts, cost_usd=0.0)
