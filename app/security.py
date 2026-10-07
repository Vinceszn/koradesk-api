"""Webhook trust: Meta signs every POST with the App Secret (SHA-256)."""

import hashlib
import hmac


def verify_signature(app_secret: str, raw_body: bytes, header: str | None) -> bool:
    """Header looks like ``sha256=<hexdigest>``. Constant-time compare."""
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))
