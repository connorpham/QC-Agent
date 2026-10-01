import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core.crypto import SecretBox


def test_roundtrip() -> None:
    box = SecretBox(Fernet.generate_key().decode())
    token = box.encrypt("JBSWY3DPEHPK3PXP")
    assert token != "JBSWY3DPEHPK3PXP"
    assert box.decrypt(token) == "JBSWY3DPEHPK3PXP"


def test_wrong_key_fails() -> None:
    token = SecretBox(Fernet.generate_key().decode()).encrypt("secret")
    with pytest.raises(InvalidToken):
        SecretBox(Fernet.generate_key().decode()).decrypt(token)
