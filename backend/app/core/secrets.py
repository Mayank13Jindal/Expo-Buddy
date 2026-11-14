from cryptography.fernet import Fernet

from app.core.config import Settings


def cipher(settings: Settings) -> Fernet:
    return Fernet(settings.encryption_key_file.read_bytes().strip())
