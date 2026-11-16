import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet() -> Fernet:
    configured = settings.FIELD_ENCRYPTION_KEY.encode()
    key = (
        configured
        if len(configured) == 44
        else base64.urlsafe_b64encode(hashlib.sha256(configured).digest())
    )
    return Fernet(key)


def encrypt_text(value: str) -> bytes:
    return _fernet().encrypt(value.encode())


def decrypt_text(value: bytes) -> str:
    try:
        return _fernet().decrypt(value).decode()
    except InvalidToken as exc:
        raise ValueError("encrypted_value_invalid") from exc
