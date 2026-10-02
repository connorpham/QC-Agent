"""Shared response-parsing helper used by both cloud adapters (finding 8)."""

import httpx
import pytest

from app.storage.base import StorageError
from app.storage.responses import (
    parsed_json,
    parsed_timestamp,
    required_header,
    required_str,
)

CONTEXT = "Uploading a file (drive x)"


def test_parsed_json_returns_the_body() -> None:
    assert parsed_json(httpx.Response(200, json={"id": "1"}), context=CONTEXT) == {"id": "1"}


def test_parsed_json_rejects_a_non_json_body() -> None:
    """A 2xx carrying HTML - a corporate proxy or a gateway page - must not raise a bare
    ``JSONDecodeError`` out of an adapter."""
    with pytest.raises(StorageError) as caught:
        parsed_json(httpx.Response(200, text="<html>not json</html>"), context=CONTEXT)
    assert (
        str(caught.value)
        == f"{CONTEXT} failed: the storage service returned an unexpected response."
    )
    assert "<html>" not in str(caught.value)  # never echoes the body


def test_parsed_json_rejects_a_json_body_that_is_not_an_object() -> None:
    with pytest.raises(StorageError):
        parsed_json(httpx.Response(200, json=[1, 2, 3]), context=CONTEXT)


def test_required_str_rejects_a_missing_field() -> None:
    with pytest.raises(StorageError):
        required_str({}, "id", context=CONTEXT)


def test_required_str_rejects_a_field_of_the_wrong_type() -> None:
    with pytest.raises(StorageError):
        required_str({"id": 123}, "id", context=CONTEXT)


def test_required_str_rejects_an_empty_string() -> None:
    with pytest.raises(StorageError):
        required_str({"id": ""}, "id", context=CONTEXT)


def test_required_str_returns_the_value() -> None:
    assert required_str({"id": "file-1"}, "id", context=CONTEXT) == "file-1"


def test_required_header_rejects_a_missing_header() -> None:
    with pytest.raises(StorageError):
        required_header(httpx.Response(302), "Location", context=CONTEXT)


def test_required_header_returns_the_value() -> None:
    response = httpx.Response(302, headers={"Location": "https://example.invalid/x"})
    assert required_header(response, "Location", context=CONTEXT) == "https://example.invalid/x"


def test_parsed_timestamp_rejects_a_missing_value() -> None:
    with pytest.raises(StorageError):
        parsed_timestamp(None, context=CONTEXT)


def test_parsed_timestamp_rejects_a_malformed_value() -> None:
    with pytest.raises(StorageError):
        parsed_timestamp("not-a-timestamp", context=CONTEXT)


def test_parsed_timestamp_parses_a_real_value() -> None:
    parsed = parsed_timestamp("2026-10-02T10:00:00.000Z", context=CONTEXT)
    assert parsed.year == 2026 and parsed.month == 10 and parsed.day == 2
