"""Offline checks used by the packaged executable's --self-test mode."""
import base64

from cryptography.fernet import Fernet, InvalidToken
from security.derivation import auth_matches, auth_token, fernet_key


def run():
    # Only fixture data. No settings, network, clipboard, tray or startup changes.
    secret = "vlink-packaged-self-test-fixture"
    cipher = Fernet(fernet_key(secret))
    payload = cipher.encrypt(b"packaged v2 roundtrip")
    if cipher.decrypt(payload) != b"packaged v2 roundtrip":
        raise RuntimeError("Protocol roundtrip failed")
    if auth_matches(secret, auth_token(secret), "2") != "2":
        raise RuntimeError("Protocol authentication failed")
    if auth_matches(secret, auth_token(secret, "1"), "1") is not None:
        raise RuntimeError("Legacy authentication enabled without opt-in")
    for version in ("1", "2"):
        exposed_key = base64.urlsafe_b64encode(bytes.fromhex(auth_token(secret, version)))
        try:
            Fernet(exposed_key).decrypt(payload)
        except InvalidToken:
            continue
        raise RuntimeError("Authentication material reveals the v2 encryption key")
