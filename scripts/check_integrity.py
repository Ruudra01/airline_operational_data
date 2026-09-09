#!/usr/bin/env python3
"""Run a data-quality SQL file against the warehouse and fail on any breach.

Contract for the SQL file: every statement returns rows shaped
`(check_name TEXT, failure_count BIGINT)`. Zero failures everywhere == exit 0.
This is what `make test-integrity` (and therefore CI) executes.

Owner: Person 5 (QA / Data Quality), plumbing by Person 7.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import text

import config


def statements(sql: str) -> list[str]:
    """Split a SQL file into executable statements.

    Each fragment keeps its inline comments but loses the leading comment
    block, otherwise a documented statement would look like a comment and be
    skipped. Splitting on `;` is fine here because these checks contain no
    semicolons inside literals or function bodies.
    """
    out: list[str] = []
    for fragment in sql.split(";"):
        lines = fragment.splitlines()
        while lines and (not lines[0].strip() or lines[0].strip().startswith("--")):
            lines.pop(0)
        statement = "\n".join(lines).strip()
        if statement:
            out.append(statement)
    return out


def run_checks(sql_path: Path, target: str = "dw") -> int:
    sql = sql_path.read_text(encoding="utf-8")
    failures: list[tuple[str, int]] = []
    passed = 0

    with config.engine_for(target).connect() as conn:
        # A single multi-statement string returns only the last result set,
        # so execute the checks one at a time.
        for statement in statements(sql):
            for row in conn.execute(text(statement)).mappings():
                name = row["check_name"]
                count = int(row["failure_count"])
                if count:
                    failures.append((name, count))
                    print(f"FAIL  {name}: {count} offending row(s)")
                else:
                    passed += 1
                    print(f"ok    {name}")

    print(f"\n{passed} check(s) passed, {len(failures)} failed")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sql_file", nargs="?", default="tests/test_integrity.sql")
    parser.add_argument("--db", default="dw", choices=["oltp", "dw"])
    args = parser.parse_args()

    path = (config.PROJECT_ROOT / args.sql_file).resolve()
    if not path.is_file():
        print(f"no such file: {path}", file=sys.stderr)
        return 1
    return run_checks(path, args.db)


if __name__ == "__main__":
    raise SystemExit(main())
