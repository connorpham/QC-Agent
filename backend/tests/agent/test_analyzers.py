import uuid

import pytest

from app.agent.analyzer import CheckBatch, CheckItem, SkipAnalyzer
from app.agent.fake import FakeAnalyzer, ScriptedVerdict


def _batch() -> CheckBatch:
    item = CheckItem(
        item_id=uuid.uuid4(),
        file_name="srs.docx",
        selected_doc_type="srs",
        title="SRS",
        outline=["# SRS"],
        preview="The system shall...",
        language="en",
    )
    other = CheckItem(
        item_id=uuid.uuid4(),
        file_name="plan.docx",
        selected_doc_type="srs",
        title="Plan",
        outline=["# Test Plan"],
        preview="Scope of testing",
        language="en",
    )
    return CheckBatch(
        project_id=uuid.uuid4(), items=[item, other], allowed_doc_types=["srs", "test-plan"]
    )


async def test_skip_analyzer_skips_everything() -> None:
    batch = _batch()
    result = await SkipAnalyzer().check(batch)
    assert [v.verdict for v in result.verdicts] == ["skipped", "skipped"]
    assert [v.item_id for v in result.verdicts] == [i.item_id for i in batch.items]


async def test_fake_analyzer_scripts_by_file_name_and_records_batches() -> None:
    fake = FakeAnalyzer(
        {"plan.docx": ScriptedVerdict("mismatch", "Looks like a test plan.", "test-plan")}
    )
    batch = _batch()
    result = await fake.check(batch)
    assert fake.batches == [batch]
    assert result.verdicts[0].verdict == "match"
    assert result.verdicts[1].verdict == "mismatch"
    assert result.verdicts[1].suggested_doc_type == "test-plan"


async def test_fake_analyzer_can_fail() -> None:
    fake = FakeAnalyzer(error=RuntimeError("agent unavailable"))
    with pytest.raises(RuntimeError):
        await fake.check(_batch())


def test_create_app_uses_skip_analyzer_by_default_and_accepts_injection() -> None:
    from app.core.config import Settings
    from app.main import create_app

    assert isinstance(create_app(Settings()).state.analyzer, SkipAnalyzer)  # type: ignore[call-arg]
    fake = FakeAnalyzer()
    assert create_app(Settings(), analyzer=fake).state.analyzer is fake  # type: ignore[call-arg]
