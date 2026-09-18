"""Versioned, purpose-separated keys; legacy v1 requires explicit opt-in."""
from __future__ import annotations

import base64
import hashlib
import hmac

PROTOCOL_VERSION = "2"
LEGACY_PROTOCOL_VERSION = "1"


def _secret_bytes(secret: str) -> bytes:
    value = (secret or "").strip().encode("utf-8")
    if not value:
        raise ValueError("Secure mode requires a shared key")
    return value


def derive_v2(secret: str, purpose: str) -> bytes:
    context = f"V-Link/{PROTOCOL_VERSION}/{purpose}".encode("ascii")
    return hmac.new(_secret_bytes(secret), context, hashlib.sha256).digest()


def encryption_key(secret: str, version: str = PROTOCOL_VERSION) -> bytes:
    if version == LEGACY_PROTOCOL_VERSION:
        return hashlib.sha256(_secret_bytes(secret)).digest()
    if version != PROTOCOL_VERSION:
        raise ValueError("Unsupported secure protocol version")
    return derive_v2(secret, "encryption")


def auth_token(secret: str, version: str = PROTOCOL_VERSION) -> str:
    if version == LEGACY_PROTOCOL_VERSION:
        return hashlib.sha256(_secret_bytes(secret)).hexdigest()
    if version != PROTOCOL_VERSION:
        raise ValueError("Unsupported secure protocol version")
    return derive_v2(secret, "authentication").hex()


def fernet_key(secret: str, version: str = PROTOCOL_VERSION) -> bytes:
    return base64.urlsafe_b64encode(encryption_key(secret, version))


def auth_matches(secret: str, provided: str, version: str | None,
                 *, allow_legacy: bool = False) -> str | None:
    requested = version or LEGACY_PROTOCOL_VERSION
    if requested not in (LEGACY_PROTOCOL_VERSION, PROTOCOL_VERSION):
        return None
    if requested == LEGACY_PROTOCOL_VERSION and not allow_legacy:
        return None
    if not isinstance(provided, str) or not provided.isascii() or len(provided) != 64:
        return None
    if hmac.compare_digest(provided, auth_token(secret, requested)):
        return requested
    return None
