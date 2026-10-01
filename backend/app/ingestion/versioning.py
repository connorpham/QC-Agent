"""Version suggestions: an existing document of the same type with a similar title (spec 5.4)."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.ingestion.naming import title_slug

SIMILARITY_THRESHOLD = 0.8


@dataclass(frozen=True)
class VersionCandidate:
    document_id: uuid.UUID
    title: str
    slug: str
    current_version: int


@dataclass(frozen=True)
class VersionSuggestion:
    document_id: uuid.UUID
    title: str
    current_version: int
    similarity: float


def suggest_versions(title: str, candidates: Iterable[VersionCandidate]) -> list[VersionSuggestion]:
    wanted = title_slug(title)
    suggestions = []
    for candidate in candidates:
        ratio = SequenceMatcher(None, wanted, candidate.slug).ratio()
        if ratio >= SIMILARITY_THRESHOLD:
            suggestions.append(
                VersionSuggestion(
                    document_id=candidate.document_id,
                    title=candidate.title,
                    current_version=candidate.current_version,
                    similarity=round(ratio, 3),
                )
            )
    suggestions.sort(key=lambda s: (-s.similarity, s.title))
    return suggestions
