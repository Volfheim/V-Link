"""Versioned key derivation for V-Link secure transport."""
from __future__ import annotations
import hashlib, hmac, base64
PROTOCOL_VERSION = "2"
LEGACY_PROTOCOL_VERSION = "1"
def _secret_bytes(secret: str) -> bytes: return (secret or "").strip().encode("utf-8")
def derive_v2(secret: str, purpose: str) -> bytes: return hmac.new(_secret_bytes(secret), f"V-Link/{PROTOCOL_VERSION}/{purpose}".encode("ascii"), hashlib.sha256).digest()
def encryption_key(secret: str, version: str = PROTOCOL_VERSION) -> bytes:
    return hashlib.sha256(_secret_bytes(secret)).digest() if version == LEGACY_PROTOCOL_VERSION else derive_v2(secret, "encryption")
def auth_token(secret: str, version: str = PROTOCOL_VERSION) -> str:
    return hashlib.sha256(_secret_bytes(secret)).hexdigest() if version == LEGACY_PROTOCOL_VERSION else hmac.new(_secret_bytes(secret), f"V-Link/{PROTOCOL_VERSION}/authentication".encode("ascii"), hashlib.sha256).hexdigest()
def fernet_key(secret: str, version: str = PROTOCOL_VERSION) -> bytes: return base64.urlsafe_b64encode(encryption_key(secret, version))
def auth_matches(secret: str, provided: str, version: str | None) -> str | None:
    requested = version or LEGACY_PROTOCOL_VERSION
    if requested == PROTOCOL_VERSION and hmac.compare_digest(provided or "", auth_token(secret, PROTOCOL_VERSION)): return PROTOCOL_VERSION
    if requested == LEGACY_PROTOCOL_VERSION and hmac.compare_digest(provided or "", auth_token(secret, LEGACY_PROTOCOL_VERSION)): return LEGACY_PROTOCOL_VERSION
    return None
