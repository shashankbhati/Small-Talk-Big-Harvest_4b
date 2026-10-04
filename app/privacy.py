import hashlib

from cryptography.fernet import Fernet

from app.config import get_settings


def hash_phone(phone: str) -> str:
    return hashlib.sha256((phone.strip() + get_settings().phone_salt).encode("utf-8")).hexdigest()


def _fernet() -> Fernet:
    key = get_settings().fernet_key
    if not key:
        raise RuntimeError("FERNET_KEY is not set")
    return Fernet(key.encode())


def encrypt_phone(phone: str) -> str:
    return _fernet().encrypt(phone.strip().encode("utf-8")).decode()


def decrypt_phone(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode("utf-8")
