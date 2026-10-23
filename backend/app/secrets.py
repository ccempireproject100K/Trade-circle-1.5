"""Encryption for secrets stored in the database (members' YouTube refresh tokens).

A refresh token is a standing key to a member's YouTube channel, so it never
sits in Mongo in plain text. Values are Fernet-encrypted (AES-128-CBC + HMAC)
with a key derived from TC_ENCRYPTION_KEY — or, until that is set, from the
JWT secret, so tokens stay encrypted either way. Changing the key makes stored
tokens unreadable; members then reconnect, the same as when a token is revoked.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


def _fernet(settings) -> Fernet:
    material = settings.encryption_key or settings.jwt_secret
    try:
        return Fernet(material.encode())
    except (ValueError, TypeError):
        # Not itself a Fernet key: derive one deterministically from the secret.
        return Fernet(base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest()))


def encrypt(settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt(settings, token: str) -> str | None:
    """The stored value, or None when it can't be read (key changed or value corrupt)."""
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken:
        return None
