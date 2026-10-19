#!/usr/bin/env python3
"""
crypto.py — Cryptography engine for Asd.

Handles master password key derivation via PBKDF2-HMAC-SHA256 (480,000 iterations)
and transparent AES encryption/decryption using Fernet.
"""

from __future__ import annotations

import base64
import os
import secrets
from typing import Optional, Tuple
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

VERIFICATION_PAYLOAD: str = "ASD_VERIFIED"
LEGACY_VERIFICATION_PAYLOAD: str = "QUICKNOTES_VERIFIED"
PBKDF2_ITERATIONS: int = 480_000
SALT_SIZE_BYTES: int = 16
KEY_LENGTH_BYTES: int = 32
MIN_MASTER_PASSWORD_LENGTH: int = 8


class CryptoError(Exception):
    """Raised when encryption or decryption operations fail."""
    pass


class CryptoManager:
    """
    Manages cryptographic lifecycle, key derivation, and symmetric encryption.
    Keeps the Fernet instance in memory only while unlocked.
    """

    def __init__(self) -> None:
        self.fernet: Optional[Fernet] = None

    @property
    def is_unlocked(self) -> bool:
        """Check whether the vault is currently unlocked."""
        return self.fernet is not None

    @staticmethod
    def derive_key(password: str, salt: bytes) -> bytes:
        """
        Derive a 32-byte Fernet-compatible key using PBKDF2HMAC-SHA256 with 480,000 iterations.
        """
        if not isinstance(password, str):
            raise TypeError("Password must be a string")
        if not isinstance(salt, (bytes, bytearray)):
            raise TypeError("Salt must be bytes")

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_LENGTH_BYTES,
            salt=salt,
            iterations=PBKDF2_ITERATIONS,
        )
        derived = kdf.derive(password.encode("utf-8"))
        return base64.urlsafe_b64encode(derived)

    def setup_master_password(self, password: str) -> Tuple[bytes, bytes]:
        """
        Generate a new salt, derive the master key, encrypt the verification payload,
        and initialize the unlocked session.
        Returns:
            (salt, verify_token)
        """
        if not password or len(password) < MIN_MASTER_PASSWORD_LENGTH:
            raise ValueError(f"Master password must be at least {MIN_MASTER_PASSWORD_LENGTH} characters long")

        salt = os.urandom(SALT_SIZE_BYTES)
        key = self.derive_key(password, salt)
        self.fernet = Fernet(key)
        verify_token = self.fernet.encrypt(VERIFICATION_PAYLOAD.encode("utf-8"))
        return salt, verify_token

    def unlock(self, password: str, salt: bytes, verify_token: bytes) -> bool:
        """
        Attempt to derive the key and verify against the encrypted token.
        On success, retains the Fernet instance in memory.
        On failure, ensures self.fernet is None.
        """
        try:
            key = self.derive_key(password, salt)
            fernet = Fernet(key)
            decrypted = fernet.decrypt(verify_token).decode("utf-8")
            if secrets.compare_digest(decrypted, VERIFICATION_PAYLOAD) or secrets.compare_digest(decrypted, LEGACY_VERIFICATION_PAYLOAD):
                self.fernet = fernet
                return True
            self.lock()
            return False
        except (InvalidToken, Exception):
            self.lock()
            return False

    def lock(self) -> None:
        """Wipe the encryption key from RAM immediately."""
        self.fernet = None

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string using the unlocked Fernet cipher.
        Returns a urlsafe base64-encoded ciphertext string.
        """
        if self.fernet is None:
            raise CryptoError("Vault is locked. Cannot encrypt data.")
        if not isinstance(plaintext, str):
            plaintext = str(plaintext)

        token = self.fernet.encrypt(plaintext.encode("utf-8"))
        return token.decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a ciphertext string back into plaintext UTF-8 string.
        """
        if self.fernet is None:
            raise CryptoError("Vault is locked. Cannot decrypt data.")
        if not isinstance(ciphertext, str):
            ciphertext = str(ciphertext)

        try:
            raw_bytes = self.fernet.decrypt(ciphertext.encode("utf-8"))
            return raw_bytes.decode("utf-8")
        except InvalidToken as exc:
            raise CryptoError("Decryption failed: invalid ciphertext or wrong key.") from exc
        except Exception as exc:
            raise CryptoError(f"Decryption error: {exc}") from exc
