from app.core.emails import is_valid_email, normalize_email


def test_normalize() -> None:
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"


def test_validity() -> None:
    assert is_valid_email("alice@example.com")
    assert not is_valid_email("alice")
    assert not is_valid_email("alice@example")
    assert not is_valid_email("a lice@example.com")
