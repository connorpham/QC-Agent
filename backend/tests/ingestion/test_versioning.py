import uuid

from app.ingestion.versioning import VersionCandidate, suggest_versions


def _candidate(title: str, slug: str, version: int = 1) -> VersionCandidate:
    return VersionCandidate(
        document_id=uuid.uuid4(), title=title, slug=slug, current_version=version
    )


def test_similar_titles_are_suggested_in_order() -> None:
    portal = _candidate("Customer Portal SRS", "customer-portal-srs", 2)
    other = _candidate("Payments Gateway SRS", "payments-gateway-srs")
    close = _candidate("Customer Portal SRS v2", "customer-portal-srs-v2")
    result = suggest_versions("Customer Portal SRS (final)", [other, close, portal])
    assert [s.document_id for s in result] == [portal.document_id, close.document_id]
    assert result[0].current_version == 2 and result[0].similarity >= 0.8


def test_unrelated_titles_are_not_suggested() -> None:
    assert (
        suggest_versions("Runbook", [_candidate("Customer Portal SRS", "customer-portal-srs")])
        == []
    )
