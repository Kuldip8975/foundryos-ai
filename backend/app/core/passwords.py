"""Password hashing and password rules (Module 5).

Hashes use scrypt from the Python standard library (no extra dependency):
a memory-hard key-derivation function with a random 16-byte salt per
password. Parameters follow the OWASP Password Storage Cheat Sheet
(N=2^15, r=8, p=3, about 32 MiB per hash). The parameters are stored in the
hash itself, so they can be raised later; :func:`needs_rehash` tells the
login code to upgrade an older hash after a successful sign-in.

Format: ``scrypt$<log2 N>$<r>$<p>$<salt b64>$<hash b64>``

Passwords are never logged, returned or stored in plain text.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

ALGORITHM = "scrypt"
SALT_BYTES = 16
KEY_BYTES = 32

MIN_LENGTH = 12
MAX_LENGTH = 128  # bounds hashing cost for very long inputs

# A short list of passwords that pass the length rule but are common choices.
_COMMON = frozenset(
    {
        "password1234",
        "password12345",
        "password123456",
        "123456789012",
        "qwertyuiop12",
        "administrator",
        "foundryos123",
        "foundryos1234",
        "welcome12345",
        "changeme1234",
        "letmein12345",
        "iloveyou1234",
    }
)


@dataclass(frozen=True)
class ScryptParams:
    log2_n: int = 15
    r: int = 8
    p: int = 3

    @property
    def maxmem(self) -> int:
        # scrypt needs 128 * r * N bytes; allow headroom.
        return 256 * self.r * (2**self.log2_n)


DEFAULT_PARAMS = ScryptParams()
# Tests lower this to keep the suite fast; production code never changes it.
_active_params = DEFAULT_PARAMS


def set_hash_params(params: ScryptParams) -> None:
    """Change the cost for new hashes (used by the test suite only)."""
    global _active_params
    _active_params = params


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _derive(password: str, salt: bytes, params: ScryptParams) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**params.log2_n,
        r=params.r,
        p=params.p,
        maxmem=params.maxmem,
        dklen=KEY_BYTES,
    )


def hash_password(password: str) -> str:
    params = _active_params
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, params)
    return f"{ALGORITHM}${params.log2_n}${params.r}${params.p}${_b64(salt)}${_b64(key)}"


def _parse(stored: str) -> tuple[ScryptParams, bytes, bytes] | None:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != ALGORITHM:
        return None
    try:
        params = ScryptParams(int(parts[1]), int(parts[2]), int(parts[3]))
        salt = base64.b64decode(parts[4], validate=True)
        key = base64.b64decode(parts[5], validate=True)
    except ValueError:
        return None
    if not (10 <= params.log2_n <= 20 and 1 <= params.r <= 32 and 1 <= params.p <= 16):
        return None
    return params, salt, key


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a stored hash."""
    if len(password) > MAX_LENGTH:
        return False
    parsed = _parse(stored)
    if parsed is None:
        return False
    params, salt, expected = parsed
    return hmac.compare_digest(_derive(password, salt, params), expected)


def needs_rehash(stored: str) -> bool:
    parsed = _parse(stored)
    return parsed is None or parsed[0] != _active_params


# A real hash of a random password: verifying against it when a username does
# not exist makes a failed sign-in take the same time either way.
_DUMMY_HASH: str | None = None


def dummy_verify(password: str) -> None:
    global _DUMMY_HASH
    if _DUMMY_HASH is None or needs_rehash(_DUMMY_HASH):
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    verify_password(password[:MAX_LENGTH], _DUMMY_HASH)


def password_problem(password: str, *, username: str | None = None) -> str | None:
    """Why ``password`` is not acceptable, or None. Messages never repeat the password."""
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    if password.strip() != password:
        return "Do not start or end the password with a space."
    if len(set(password)) < 5:
        return "Use a less repetitive password."
    lowered = password.lower()
    if lowered in _COMMON:
        return "This password is too common. Choose another."
    if username and len(username) >= 3 and username.lower() in lowered:
        return "The password must not contain the username."
    return None


def generate_temporary_password() -> str:
    """A random one-time password (about 120 bits) that satisfies the rules."""
    while True:
        candidate = secrets.token_urlsafe(15)  # 20 URL-safe characters
        if password_problem(candidate) is None:
            return candidate