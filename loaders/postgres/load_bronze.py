"""Load Bronze JSON files into PostgreSQL bronze schema via UPSERT."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import Json

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection

load_dotenv()

logger = logging.getLogger(__name__)

GITHUB_BRONZE_DIR = Path("data/bronze/github_repos")
OPENDIGGER_BRONZE_DIR = Path("data/bronze/opendigger")

# Mirrors extractors.opendigger.METRICS — kept local to avoid cross-module coupling.
_OPENDIGGER_METRICS: list[str] = [
    "openrank",
    "stars",
    "forks",
    "issues_new",
    "issues_closed",
    "participants",
]


def get_conn() -> PgConnection:
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "hybridrag_forge"),
        user=os.getenv("POSTGRES_USER", "forge_user"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


def _parse_opendigger_stem(stem: str) -> tuple[str, str, str] | None:
    """Parse '{owner}_{repo}_{metric}' stem into (owner, repo, metric).

    GitHub owner names cannot contain underscores, so splitting on the first
    underscore always isolates the owner from the rest of the filename.
    """
    for metric in _OPENDIGGER_METRICS:
        if stem.endswith(f"_{metric}"):
            owner_repo = stem[: -(len(metric) + 1)]
            parts = owner_repo.split("_", 1)
            if len(parts) == 2:
                return parts[0], parts[1], metric
    return None


def load_github_repos(
    bronze_dir: Path = GITHUB_BRONZE_DIR,
    conn: PgConnection | None = None,
) -> int:
    """Upsert all github_repos JSON files from *bronze_dir* into PostgreSQL.

    When *conn* is None a fresh connection is opened, committed, and closed.
    When *conn* is provided the caller owns transaction lifecycle and connection.
    """
    files = sorted(bronze_dir.glob("*.json"))
    if not files:
        logger.info("No github_repos JSON files found in %s", bronze_dir)
        return 0

    sql = """
        INSERT INTO bronze.github_repos (repo_owner, repo_name, fetched_at, raw_data)
        VALUES (%(owner)s, %(name)s, %(fetched_at)s, %(raw_data)s)
        ON CONFLICT (repo_owner, repo_name)
        DO UPDATE SET
            fetched_at = EXCLUDED.fetched_at,
            raw_data   = EXCLUDED.raw_data
    """

    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    assert conn is not None

    count = 0
    try:
        with conn.cursor() as cur:
            for path in files:
                try:
                    payload = json.loads(path.read_text())
                    owner = payload["owner"]
                    name = payload["repo"]
                    fetched_at = payload.get("fetched_at", datetime.now(UTC).isoformat())
                    cur.execute(
                        sql,
                        {
                            "owner": owner,
                            "name": name,
                            "fetched_at": fetched_at,
                            "raw_data": Json(payload),
                        },
                    )
                    count += 1
                    logger.debug("Upserted github_repos %s/%s", owner, name)
                except Exception:
                    logger.exception("Failed to load %s", path)
        if own_conn:
            conn.commit()
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()

    logger.info("Loaded %d github_repos records", count)
    return count


def load_opendigger_metrics(
    bronze_dir: Path = OPENDIGGER_BRONZE_DIR,
    conn: PgConnection | None = None,
) -> int:
    """Upsert all opendigger JSON files from *bronze_dir* into PostgreSQL.

    Filename convention: {owner}_{repo}_{metric}.json
    When *conn* is None a fresh connection is opened, committed, and closed.
    When *conn* is provided the caller owns transaction lifecycle and connection.
    """
    files = sorted(bronze_dir.glob("*.json"))
    if not files:
        logger.info("No opendigger JSON files found in %s", bronze_dir)
        return 0

    sql = """
        INSERT INTO bronze.opendigger_metrics
            (repo_owner, repo_name, metric_name, fetched_at, raw_data)
        VALUES (%(owner)s, %(name)s, %(metric)s, %(fetched_at)s, %(raw_data)s)
        ON CONFLICT (repo_owner, repo_name, metric_name)
        DO UPDATE SET
            fetched_at = EXCLUDED.fetched_at,
            raw_data   = EXCLUDED.raw_data
    """

    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    assert conn is not None

    count = 0
    try:
        with conn.cursor() as cur:
            for path in files:
                try:
                    parsed = _parse_opendigger_stem(path.stem)
                    if parsed is None:
                        logger.warning("Cannot determine metric from filename: %s", path.name)
                        continue
                    owner, repo, metric = parsed
                    payload = json.loads(path.read_text())
                    cur.execute(
                        sql,
                        {
                            "owner": owner,
                            "name": repo,
                            "metric": metric,
                            "fetched_at": datetime.now(UTC).isoformat(),
                            "raw_data": Json(payload),
                        },
                    )
                    count += 1
                    logger.debug("Upserted opendigger %s/%s metric=%s", owner, repo, metric)
                except Exception:
                    logger.exception("Failed to load %s", path)
        if own_conn:
            conn.commit()
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()

    logger.info("Loaded %d opendigger_metrics records", count)
    return count


def load_all() -> None:
    load_github_repos()
    load_opendigger_metrics()


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    load_all()
