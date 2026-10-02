"""The live suite must stay opt-in: an ordinary run is offline, free and parameterised on
localfs alone. These tests check the switch, not the live services."""

import pytest

from tests.storage import live


def test_live_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(live.LIVE_FLAG, raising=False)
    assert live.live_enabled() is False
    assert live.live_params() == []


@pytest.mark.parametrize("value", ["0", "", "true", "yes"])
def test_only_the_exact_flag_enables_live_tests(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """A half-set variable must not start charging money against a customer tenant."""
    monkeypatch.setenv(live.LIVE_FLAG, value)
    assert live.live_enabled() is False


def test_the_flag_adds_both_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(live.LIVE_FLAG, "1")
    assert live.live_params() == ["sharepoint", "gdrive"]


def test_a_missing_credential_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silently skipping would make a green run look like proof the adapters work."""
    monkeypatch.delenv("QC_LIVE_SP_TENANT_ID", raising=False)
    with pytest.raises(RuntimeError, match="QC_LIVE_SP_TENANT_ID"):
        live.require("QC_LIVE_SP_TENANT_ID")


def test_no_credential_value_is_committed() -> None:
    """The repository must never contain a tenant, site, drive id or key."""
    source = (live.__file__,)
    for path in source:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
        assert "BEGIN PRIVATE KEY" not in text
        assert ".sharepoint.com," not in text
