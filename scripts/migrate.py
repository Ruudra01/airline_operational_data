#!/usr/bin/env python3
"""Flyway-style SQL migration runner (owner: Person 7).

Applies every `*.sql` file in a directory, in filename order, inside one
transaction per file, and records what it applied in `schema_version` - the
same contract Flyway uses (version, description, checksum, applied_at,
success). Re-running is a no-op, so `make migrate` is safe to repeat.

Naming: `V<version>__<description>.sql` (e.g. `V1__initial_schema.sql`).
Files without the `V` prefix (the warehouse DDL) are versioned by filename,
which is why the star-schema files sort dimensions-before-fact naturally
(`dim_*` < `fact_*`).

    python scripts/migrate.py --db oltp --dir oltp/migrations
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import re
import sys
from pathlib import Path

from sqlalchemy import text

import config

LOG = logging.getLogger("migrate")

HISTORY_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    installed_rank SERIAL       PRIMARY KEY,
    version        TEXT         NOT NULL UNIQUE,
    description    TEXT         NOT NULL,
    script         TEXT         NOT NULL,
    checksum       TEXT         NOT NULL,
    applied_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    execution_ms   INTEGER      NOT NULL,
    success        BOOLEAN      NOT NULL DEFAULT TRUE
);
"""

VERSIONED = re.compile(r"^V(?P<version>[\d._]+)__(?P<description>.+)\.sql$", re.IGNORECASE)


def parse_name(path: Path) -> tuple[str, str]:
    """Return (version, description) for a migration file."""
    match = VERSIONED.match(path.name)
    if match:
        return match.group("version"), match.group("description").replace("_", " ")
    # Un-versioned DDL (warehouse/, staging/): the filename *is* the version.
    return path.stem, path.stem.replace("_", " ")


def sort_key(path: Path) -> tuple[int, tuple, str]:
    """Numeric ordering for V-prefixed files, alphabetical for the rest."""
    match = VERSIONED.match(path.name)
    if match:
        parts = tuple(int(p) for p in re.split(r"[._]", match.group("version")) if p.isdigit())
        return (0, parts, path.name)
    return (1, (), path.name)


def checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:32]


def applied_versions(conn) -> dict[str, str]:
    rows = conn.execute(
        text("SELECT version, checksum FROM schema_version WHERE success")
    ).all()
    return {row.version: row.checksum for row in rows}


def migrate(target: str, directory: Path) -> int:
    files = sorted((p for p in directory.glob("*.sql")), key=sort_key)
    if not files:
        LOG.warning("no .sql files found in %s", directory)
        return 0

    engine = config.engine_for(target)
    with engine.begin() as conn:
        conn.execute(text(HISTORY_DDL))
        already = applied_versions(conn)

    applied = 0
    for path in files:
        version, description = parse_name(path)
        sql = path.read_text(encoding="utf-8")
        digest = checksum(sql)

        if version in already:
            if already[version] != digest:
                # Flyway fails hard here; so do we. Editing an applied
                # migration means two environments no longer share a schema.
                raise SystemExit(
                    f"checksum mismatch for {path.name}: it was already applied to "
                    f"'{target}' with different content. Add a new V<n>__ file instead."
                )
            LOG.info("skip   %-34s (already applied)", path.name)
            continue

        LOG.info("apply  %-34s -> %s", path.name, target)
        import time

        started = time.perf_counter()
        with engine.begin() as conn:  # one transaction per migration
            conn.exec_driver_sql(sql)
            conn.execute(
                text(
                    """
                    INSERT INTO schema_version
                        (version, description, script, checksum, execution_ms, success)
                    VALUES (:v, :d, :s, :c, :ms, TRUE)
                    """
                ),
                {
                    "v": version,
                    "d": description,
                    "s": path.name,
                    "c": digest,
                    "ms": int((time.perf_counter() - started) * 1000),
                },
            )
        applied += 1

    LOG.info("%s: %d applied, %d skipped", target, applied, len(files) - applied)
    return applied


def main() -> int:
    config.configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, choices=["oltp", "dw"])
    parser.add_argument("--dir", required=True, help="Directory containing *.sql files")
    args = parser.parse_args()

    directory = (config.PROJECT_ROOT / args.dir).resolve()
    if not directory.is_dir():
        print(f"not a directory: {directory}", file=sys.stderr)
        return 1

    migrate(args.db, directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
