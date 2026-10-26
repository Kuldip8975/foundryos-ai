"""Access tokens for the workflow assistant (Module 4).

There is no user database yet, so people are configured in the environment:

    WORKFLOW_ACCESS_TOKENS=alice:supervisor:<sha256 hex>,bob:operator:<sha256 hex>

Each entry holds a name, a role and the SHA-256 of a random bearer token. Only
hashes are configured; tokens are generated once by
``python -m app.cli.workflow_token`` and given to the person. Lookups compare
hashes in constant time and check every entry, so timing does not reveal
which entry matched.

This module deliberately imports nothing from the application, so the settings
module can use it to validate configuration at startup.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from app.models.enums import WorkflowRole

NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{0,99}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
MIN_TOKEN_LENGTH = 24
MAX_TOKEN_LENGTH = 200


@dataclass(frozen=True)
class AccessEntry:
    name: str
    role: WorkflowRole
    token_hash: str

    def __repr__(self) -> str:  # never print the hash
        return f"AccessEntry(name={self.name!r}, role={self.role.value!r})"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_token() -> str:
    """A new random bearer token (256 bits, URL-safe)."""
    return secrets.token_urlsafe(32)


def parse_access_entries(raw: str) -> tuple[AccessEntry, ...]:
    """Parse ``name:role:hash`` entries. Errors name the entry number, never its content."""
    entries: list[AccessEntry] = []
    seen_hashes: set[str] = set()
    seen_names: set[str] = set()
    for position, chunk in enumerate((part.strip() for part in raw.split(",")), start=1):
        if not chunk:
            continue
        parts = chunk.split(":")
        if len(parts) != 3:
            raise ValueError(
                f"WORKFLOW_ACCESS_TOKENS entry {position} must look like name:role:sha256"
            )
        name, role, token_hash = (part.strip() for part in parts)
        if not NAME_PATTERN.match(name):
            raise ValueError(f"WORKFLOW_ACCESS_TOKENS entry {position} has an invalid name")
        try:
            parsed_role = WorkflowRole(role)
        except ValueError:
            allowed = ", ".join(r.value for r in WorkflowRole)
            raise ValueError(
                f"WORKFLOW_ACCESS_TOKENS entry {position} has an unknown role (use {allowed})"
            ) from None
        token_hash = token_hash.lower()
        if not _HASH.match(token_hash):
            raise ValueError(
                f"WORKFLOW_ACCESS_TOKENS entry {position} must end with a 64-character "
                "SHA-256 hex digest (generate one with python -m app.cli.workflow_token)"
            )
        if token_hash in seen_hashes or name in seen_names:
            raise ValueError(f"WORKFLOW_ACCESS_TOKENS entry {position} repeats a name or token")
        seen_hashes.add(token_hash)
        seen_names.add(name)
        entries.append(AccessEntry(name=name, role=parsed_role, token_hash=token_hash))
    return tuple(entries)


def authenticate(entries: tuple[AccessEntry, ...], token: str) -> AccessEntry | None:
    """The entry whose hash matches ``token``, or None."""
    if not (MIN_TOKEN_LENGTH <= len(token) <= MAX_TOKEN_LENGTH):
        return None
    candidate = hash_token(token)
    match: AccessEntry | None = None
    for entry in entries:  # no early exit: every entry is compared
        if hmac.compare_digest(candidate, entry.token_hash):
            match = entry
    return match