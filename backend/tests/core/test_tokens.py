from app.core.tokens import hash_token, new_session_token


def test_tokens_are_random_and_long() -> None:
    assert len(new_session_token()) >= 40
    assert new_session_token() != new_session_token()


def test_hash_is_deterministic_and_keyed() -> None:
    assert hash_token("t", "s1") == hash_token("t", "s1")
    assert hash_token("t", "s1") != hash_token("t", "s2")
    assert len(hash_token("t", "s1")) == 64
