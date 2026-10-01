from app.core.passwords import (
    MIN_PASSWORD_LENGTH,
    burn_password_check,
    generate_temporary_password,
    hash_password,
    validate_new_password,
    verify_password,
)


def test_hash_and_verify_roundtrip() -> None:
    hashed = hash_password("correct-horse-battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct-horse-battery") is True
    assert verify_password(hashed, "wrong-password-123") is False


def test_verify_rejects_malformed_hash() -> None:
    assert verify_password("not-a-hash", "anything") is False


def test_policy_rejects_short_password() -> None:
    errors = validate_new_password("short", email="alice@example.com")
    assert f"Password must be at least {MIN_PASSWORD_LENGTH} characters." in errors


def test_policy_rejects_email_local_part() -> None:
    errors = validate_new_password("my-alice-password-1", email="Alice@example.com")
    assert "Password must not contain your e-mail name." in errors


def test_policy_accepts_good_password() -> None:
    assert validate_new_password("a-very-long-passphrase", email="alice@example.com") == []


def test_temporary_password_is_long_and_random() -> None:
    first, second = generate_temporary_password(), generate_temporary_password()
    assert len(first) >= MIN_PASSWORD_LENGTH
    assert first != second


def test_burn_password_check_returns_none_and_does_not_raise() -> None:
    result = burn_password_check("anything")
    assert result is None
