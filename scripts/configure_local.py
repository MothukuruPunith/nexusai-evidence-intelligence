"""Create local credentials once, without printing them or replacing an existing file."""

import os
import secrets
from pathlib import Path


def main() -> None:
    port = int(os.environ.get("NEXUS_DB_PORT", "55432"))
    if not 1024 <= port <= 65535:
        raise SystemExit("NEXUS_DB_PORT must be between 1024 and 65535")
    passwords = {name: secrets.token_hex(24) for name in ("bootstrap", "owner", "writer", "reader")}
    lines = [
        "POSTGRES_DB=nexusai",
        "POSTGRES_USER=nexus_bootstrap",
        f"POSTGRES_PASSWORD={passwords['bootstrap']}",
        f"NEXUS_DB_PORT={port}",
    ]
    for variable, role in (
        ("ADMIN", "bootstrap"),
        ("MIGRATION", "owner"),
        ("", "writer"),
        ("ANALYTICS", "reader"),
    ):
        name = f"NEXUS_{variable + '_' if variable else ''}DATABASE_URL"
        lines.append(
            f"{name}=postgresql+psycopg://nexus_{role}:{passwords[role]}@127.0.0.1:{port}/nexusai"
        )
    try:
        descriptor = os.open(Path(".env"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(".env already exists; left unchanged") from None
    with os.fdopen(descriptor, "w") as handle:
        handle.write("\n".join(lines) + "\n")
    print("Created private .env with unique local credentials.")


if __name__ == "__main__":
    main()
