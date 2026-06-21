"""Parse Bronze dependency manifests and load them into the Silver layer.

dbt-postgres cannot parse TOML/Python source, so this loader does the
manifest parsing in Python (via transformers.dependency_parser) and writes
the result directly into silver.repo_dependency. dbt treats that table as a
tested source (see dbt/models/silver/sources.yml) rather than a dbt model.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import psycopg2

from transformers.dependency_parser import (
    parse_pyproject_toml,
    parse_requirements_txt,
    parse_setup_py,
)

if TYPE_CHECKING:
    from psycopg2.extensions import connection as PgConnection

logger = logging.getLogger(__name__)

_PARSERS = {
    "pyproject_toml": parse_pyproject_toml,
    "requirements_txt": parse_requirements_txt,
    "setup_py": parse_setup_py,
}


def get_conn() -> PgConnection:
    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "hybridrag_forge"),
        user=os.getenv("POSTGRES_USER", "forge_user"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
    )


def _blob_text(blob: dict[str, Any] | None) -> str | None:
    """Extract the text of a GitHub GraphQL Blob object, if present."""
    return blob.get("text") if blob else None


def load_repo_dependencies(conn: PgConnection | None = None) -> int:
    """Parse manifests in bronze.github_repos and replace silver.repo_dependency rows.

    For each (repo, manifest type) the existing rows are deleted and replaced
    with the freshly parsed set, so removed dependencies don't linger.
    When *conn* is None a fresh connection is opened, committed, and closed.
    When *conn* is provided the caller owns transaction lifecycle and connection.
    """
    own_conn = conn is None
    if own_conn:
        conn = get_conn()
    assert conn is not None

    count = 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT repo_owner, repo_name, raw_data FROM bronze.github_repos")
            repos = cur.fetchall()

        for repo_owner, repo_name, raw_data in repos:
            try:
                repository = (raw_data.get("data") or {}).get("repository") or {}
                with conn.cursor() as cur:
                    for source_manifest, parse in _PARSERS.items():
                        package_names = parse(_blob_text(repository.get(source_manifest)))
                        cur.execute(
                            """
                            DELETE FROM silver.repo_dependency
                            WHERE repo_owner = %s AND repo_name = %s AND source_manifest = %s
                            """,
                            (repo_owner, repo_name, source_manifest),
                        )
                        for package_name in package_names:
                            cur.execute(
                                """
                                INSERT INTO silver.repo_dependency
                                    (repo_owner, repo_name, source_manifest, package_name, loaded_at)
                                VALUES (%s, %s, %s, %s, %s)
                                ON CONFLICT (repo_owner, repo_name, source_manifest, package_name)
                                DO NOTHING
                                """,
                                (
                                    repo_owner,
                                    repo_name,
                                    source_manifest,
                                    package_name,
                                    datetime.now(UTC),
                                ),
                            )
                            count += 1
                logger.debug("Loaded dependencies for %s/%s", repo_owner, repo_name)
            except Exception:
                logger.exception("Failed to load dependencies for %s/%s", repo_owner, repo_name)

        if own_conn:
            conn.commit()
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()

    logger.info("Loaded %d repo_dependency rows", count)
    return count


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    load_repo_dependencies()
