#!/usr/bin/env python3
"""Block until both databases accept connections (owner: Person 7).

`docker compose up -d` returns before Postgres finishes initdb, so every
`make` target that touches a database runs after this gate.
"""

from __future__ import annotations

import argparse
import sys
import time

import config


def wait(target: str, timeout: float, interval: float = 1.0) -> bool:
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        if config.ping(target):
            print(f"{target}: ready after {attempt} attempt(s)")
            return True
        time.sleep(interval)
    print(f"{target}: NOT ready after {timeout:.0f}s", file=sys.stderr)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        action="append",
        choices=["oltp", "dw"],
        help="Database to wait for (repeatable). Default: both.",
    )
    parser.add_argument("--timeout", type=float, default=90.0, help="Seconds per database")
    args = parser.parse_args()

    targets = args.db or ["oltp", "dw"]
    return 0 if all(wait(t, args.timeout) for t in targets) else 1


if __name__ == "__main__":
    raise SystemExit(main())
