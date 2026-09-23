from functools import lru_cache

from cryptography.fernet import Fernet
from sqlalchemy.types import String, TypeDecorator

from app.config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().encryption_key.encode())


class EncryptedString(TypeDecorator):
    """Transparently encrypts/decrypts a string column at rest using Fernet.

    Stored as ciphertext in the database; call sites see plaintext.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _fernet().decrypt(value.encode()).decode()
