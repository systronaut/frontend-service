# Author: Systronaut
# Reversible secret storage for hypervisor credentials.
#
# Hypervisor passwords/tokens must be *decryptable* (we use them to connect), so
# this is symmetric encryption, NOT password hashing. Fernet (AES-128-CBC +
# HMAC) embeds a random IV in every token, so two identical secrets encrypt to
# different ciphertexts -- that is the per-record "salt". The master key comes
# from CONTROL_PLANE_FERNET_KEY; if unset it is derived from CONTROL_PLANE_SECRET
# so the app still works, but production MUST set a dedicated key (rotating
# CONTROL_PLANE_SECRET would otherwise make stored creds undecryptable).

import base64
import hashlib
import os


class SecretError(RuntimeError):
    """Raised when a secret cannot be encrypted/decrypted."""


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # pragma: no cover
        raise SecretError("cryptography is not installed (pip install cryptography).") from exc

    key = os.environ.get("CONTROL_PLANE_FERNET_KEY", "").strip()
    if key:
        return Fernet(key.encode())
    # Fallback: derive a stable Fernet key from the Flask secret.
    seed = os.environ.get("CONTROL_PLANE_SECRET", "") or "systronaut-dev-secret"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()   # 32 bytes
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for at-rest storage; returns a urlsafe token string."""
    if plaintext is None:
        plaintext = ""
    try:
        return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    except SecretError:
        raise
    except Exception as exc:  # pragma: no cover
        raise SecretError(f"encrypt failed: {exc}") from exc


def decrypt(token: str) -> str:
    """Decrypt a token produced by encrypt(); raises SecretError on tamper/key mismatch."""
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except SecretError:
        raise
    except Exception as exc:
        raise SecretError("decrypt failed (wrong key or corrupted secret).") from exc


def new_key() -> str:
    """Generate a fresh Fernet key (for CONTROL_PLANE_FERNET_KEY)."""
    from cryptography.fernet import Fernet
    return Fernet.generate_key().decode("ascii")
