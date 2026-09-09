"""Centralised configuration and connection manager.

Single source of truth for every database connection in the platform. No
module anywhere else in this repo is allowed to build a connection string;
they all call :func:`oltp_engine` / :func:`dw_engine` from here, and those
read exclusively from environment variables (loaded from `.env`).

Owner: Person 7 (Platform / DevOps).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

# Repo root == the directory holding this file.
PROJECT_ROOT = Path(__file__).resolve().parent

# `.env` is optional (CI injects real env vars instead), and never overrides
# a variable that is already set in the environment.
load_dotenv(PROJECT_ROOT / ".env", override=False)


# --------------------------------------------------------------------------
# Environment helpers
# --------------------------------------------------------------------------
def env(name: str, default: str | None = None, *, required: bool = False) -> str:
    """Return an environment variable, failing loudly when it is mandatory."""
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(
            f"Environment variable {name} is not set. "
            f"Copy .env.example to .env (or run `make env`) and try again."
        )
    return value or ""


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


# --------------------------------------------------------------------------
# Connection URLs (env-driven, never hardcoded)
# --------------------------------------------------------------------------
def oltp_url() -> str:
    """SQLAlchemy URL for the 3NF operational database."""
    return env(
        "OLTP_DB_URL",
        "postgresql+psycopg2://airline:airline@localhost:5432/airline_oltp",
    )


def dw_url() -> str:
    """SQLAlchemy URL for the star-schema warehouse."""
    return env(
        "DW_DB_URL",
        "postgresql+psycopg2://airline:airline@localhost:5433/airline_dw",
    )


# --------------------------------------------------------------------------
# Engines
# --------------------------------------------------------------------------
# Engines are cached per-URL: SQLAlchemy engines own a connection pool, so
# creating one per call would leak sockets in the loaders.
_ENGINES: dict[str, Engine] = {}


def _engine(url: str) -> Engine:
    if url not in _ENGINES:
        _ENGINES[url] = create_engine(url, future=True, pool_pre_ping=True)
    return _ENGINES[url]


def oltp_engine() -> Engine:
    return _engine(oltp_url())


def dw_engine() -> Engine:
    return _engine(dw_url())


def engine_for(target: str) -> Engine:
    """Resolve the string names used by the CLI scripts ("oltp" / "dw")."""
    target = target.lower()
    if target == "oltp":
        return oltp_engine()
    if target in {"dw", "warehouse"}:
        return dw_engine()
    raise ValueError(f"Unknown database target {target!r} (expected 'oltp' or 'dw')")


@contextmanager
def connection(target: str) -> Iterator[Connection]:
    """Transactional connection to `target`; commits on success, rolls back on error."""
    with engine_for(target).begin() as conn:
        yield conn


def ping(target: str) -> bool:
    """True when `target` accepts queries. Used by scripts/wait_for_db.py."""
    try:
        with engine_for(target).connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - any driver error means "not ready yet"
        return False


# --------------------------------------------------------------------------
# ELT behaviour knobs
# --------------------------------------------------------------------------
#: Service date applied when a staging timestamp has no date part.
DEFAULT_SERVICE_DATE = env("SERVICE_DATE", "2026-09-09")

#: Allowed drift between the raw `duration` string and the recomputed value.
DURATION_TOLERANCE_MINUTES = env_int("DURATION_TOLERANCE_MINUTES", 0)

#: Directory for inspectable ELT artifacts (clean rows, rejects).
DATA_DIR = PROJECT_ROOT / env("DATA_DIR", "data")


def configure_logging() -> None:
    """Uniform log format for every entry point."""
    logging.basicConfig(
        level=getattr(logging, env("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-7s %(name)-22s %(message)s",
        datefmt="%H:%M:%S",
    )


if __name__ == "__main__":  # pragma: no cover - manual smoke check
    configure_logging()
    print("OLTP:", oltp_url(), "reachable:", ping("oltp"))
    print("DW  :", dw_url(), "reachable:", ping("dw"))
