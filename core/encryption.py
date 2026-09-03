import os

from cryptography.fernet import Fernet


def get_cipher() -> Fernet:
    """Get the Fernet cipher instance based on the ENCRYPTION_KEY env var."""
    key = os.environ.get("ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("ENCRYPTION_KEY environment variable is not set. Please set it to a valid Fernet key.")
    try:
        return Fernet(key.encode("utf-8"))
    except ValueError as e:
        raise RuntimeError(f"Invalid ENCRYPTION_KEY: {e}") from e


def encrypt_key(plaintext: str) -> str:
    """Encrypt a string (API key) and return the base64 Fernet token."""
    if not plaintext:
        return ""
    cipher = get_cipher()
    token = cipher.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_key(ciphertext: str) -> str:
    """Decrypt a Fernet token back to the original string (API key)."""
    if not ciphertext:
        return ""
    cipher = get_cipher()
    plaintext = cipher.decrypt(ciphertext.encode("utf-8"))
    return plaintext.decode("utf-8")


def redact_key(key: str) -> str:
    """Return a redacted version of the key showing only the first 4 and last 4 characters."""
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}...{key[-4:]}"
