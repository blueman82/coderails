"""Identify a native encrypted message that cannot be checked as prompt text."""

from __future__ import annotations

import base64
import binascii
import re


def is_opaque(message: str) -> bool:
    """Recognize the observed single-line Fernet wire shape without decrypting it."""
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", message):
        return False
    try:
        raw = base64.b64decode(message, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        return False
    return len(raw) >= 73 and raw[0] == 0x80 and (len(raw) - 57) % 16 == 0
