from datetime import UTC, datetime, timedelta

import pyotp

from app.core.totp import (
    generate_recovery_codes,
    hash_recovery_code,
    is_recovery_code_format,
    match_totp,
    new_totp_secret,
    provisioning_uri,
)

NOW = datetime(2026, 10, 1, 9, 0, 15, tzinfo=UTC)


def test_current_code_matches_and_returns_counter() -> None:
    secret = new_totp_secret()
    code = pyotp.TOTP(secret).at(NOW)
    assert match_totp(secret, code, now=NOW) == pyotp.TOTP(secret).timecode(NOW)


def test_previous_step_is_accepted_two_steps_back_is_not() -> None:
    secret = new_totp_secret()
    totp = pyotp.TOTP(secret)
    assert match_totp(secret, totp.at(NOW - timedelta(seconds=30)), now=NOW) is not None
    assert match_totp(secret, totp.at(NOW - timedelta(seconds=60)), now=NOW) is None


def test_forward_step_is_accepted_two_steps_forward_is_not() -> None:
    secret = new_totp_secret()
    totp = pyotp.TOTP(secret)
    assert match_totp(secret, totp.at(NOW + timedelta(seconds=30)), now=NOW) is not None
    assert match_totp(secret, totp.at(NOW + timedelta(seconds=60)), now=NOW) is None


def test_bad_codes_are_rejected() -> None:
    secret = new_totp_secret()
    assert match_totp(secret, "12345", now=NOW) is None
    assert match_totp(secret, "abcdef", now=NOW) is None


def test_code_with_spaces_is_accepted() -> None:
    secret = new_totp_secret()
    code = pyotp.TOTP(secret).at(NOW)
    assert match_totp(secret, f"{code[:3]} {code[3:]}", now=NOW) is not None


def test_provisioning_uri_names_issuer_and_account() -> None:
    uri = provisioning_uri(new_totp_secret(), "alice@example.com")
    assert uri.startswith("otpauth://totp/")
    assert "issuer=QC-Agent" in uri
    assert "alice%40example.com" in uri


def test_recovery_codes() -> None:
    codes = generate_recovery_codes()
    secret = new_totp_secret()
    assert len(codes) == 10
    assert len(set(codes)) == 10
    assert all(is_recovery_code_format(c) for c in codes)
    normalized_code = f"  {codes[0].upper()} "
    assert hash_recovery_code(codes[0], secret) == hash_recovery_code(normalized_code, secret)
    assert hash_recovery_code(codes[0], secret) != hash_recovery_code(codes[0], new_totp_secret())
    assert is_recovery_code_format("123456") is False
