"""Create an access token for the workflow assistant (Module 4).

    cd backend
    python -m app.cli.workflow_token alice supervisor

Prints a new random token (give it to that person; it is shown only once) and
the ``name:role:sha256`` entry to add to WORKFLOW_ACCESS_TOKENS in your .env.
Nothing is written anywhere and no database is touched.
"""

from __future__ import annotations

import argparse
import sys

from app.core.security import NAME_PATTERN, generate_token, hash_token
from app.models.enums import WorkflowRole


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a workflow assistant access token.")
    parser.add_argument("name", help="Person or account name, e.g. alice")
    parser.add_argument("role", choices=[role.value for role in WorkflowRole])
    args = parser.parse_args(argv)

    if not NAME_PATTERN.match(args.name):
        print("Name: letters, digits, '.', '_', '@' or '-' (max 100).", file=sys.stderr)
        return 2

    token = generate_token()
    print(f"Token for {args.name} (shown once; paste it into the assistant's sign-in box):")
    print(f"  {token}")
    print()
    print("Add this entry to WORKFLOW_ACCESS_TOKENS in .env (comma-separate several entries):")
    print(f"  {args.name}:{args.role}:{hash_token(token)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())