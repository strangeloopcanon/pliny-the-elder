from __future__ import annotations

import hashlib
from typing import Iterable


def deterministic_hash(value: str, *, salt: str = "vei") -> str:
    text = f"{salt}:{value}".encode("utf-8")
    return hashlib.sha256(text).hexdigest()[:12]


def pseudonymize_email(email: str, *, salt: str = "vei") -> str:
    local, _, domain = email.partition("@")
    hashed = deterministic_hash(local, salt=salt)
    domain_hash = deterministic_hash(domain or "example", salt=salt)
    return f"user-{hashed}@{domain_hash}.example"


def pseudonymize_name(name: str, *, salt: str = "vei") -> str:
    return f"User-{deterministic_hash(name, salt=salt)}"


def redact_numeric_sequences(text: str) -> str:
    out = []
    digits = 0
    for ch in text:
        if ch.isdigit():
            digits += 1
            if digits > 4:
                continue
        else:
            digits = 0
        out.append(ch)
    return "".join(out)
