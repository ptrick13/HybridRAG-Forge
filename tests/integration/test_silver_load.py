"""Integration tests for loaders/postgres/load_silver.py.

Requires Docker. Each test spins up a throw-away PostgreSQL container via
testcontainers, initialises the bronze and silver schemas, seeds a Bronze
row directly, then asserts load_repo_dependencies() behaves correctly
including idempotency and removal of stale dependencies.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import Json

from loaders.postgres.load_silver import load_repo_dependencies

BRONZE_SCHEMA_SQL = Path(__file__).parent.parent.parent / "scripts" / "init_bronze_schema.sql"
SILVER_SCHEMA_SQL = Path(__file__).parent.parent.parent / "scripts" / "init_silver_schema.sql"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_psycopg2_conn(pg):
    """Return a psycopg2 connection to a testcontainers PostgresContainer."""
    url = pg.get_connection_url()
    dsn = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return psycopg2.connect(dsn)


def _row_count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        return cur.fetchone()[0]


def _insert_bronze_repo(conn, owner: str, name: str, raw_data: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO bronze.github_repos (repo_owner, repo_name, fetched_at, raw_data)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (repo_owner, repo_name)
            DO UPDATE SET raw_data = EXCLUDED.raw_data
            """,
            (owner, name, datetime.now(UTC), Json(raw_data)),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg():
    """Start a PostgreSQL container and initialise the bronze + silver schemas once."""
    pytest.importorskip("testcontainers", reason="testcontainers not installed")
    from testcontainers.postgres import PostgresContainer

    if shutil.which("docker") is None:
        pytest.skip("Docker not available")

    with PostgresContainer("postgres:16-alpine") as container:
        conn = _make_psycopg2_conn(container)
        try:
            with conn.cursor() as cur:
                cur.execute(BRONZE_SCHEMA_SQL.read_text())
                cur.execute(SILVER_SCHEMA_SQL.read_text())
            conn.commit()
        finally:
            conn.close()
        yield container


@pytest.fixture
def db_conn(pg):
    """Fresh psycopg2 connection per test; auto-closed on teardown."""
    conn = _make_psycopg2_conn(pg)
    yield conn
    conn.rollback()
    conn.close()


_RAW_DATA = {
    "data": {
        "repository": {
            "pyproject_toml": {
                "text": '[project]\ndependencies = ["httpx>=0.28", "pydantic==2.13.4"]\n'
            },
            "requirements_txt": None,
            "setup_py": None,
        }
    }
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadRepoDependencies:
    def test_inserts_parsed_dependencies(self, db_conn):
        _insert_bronze_repo(db_conn, "acme", "demo", _RAW_DATA)

        count = load_repo_dependencies(conn=db_conn)
        db_conn.commit()

        assert count == 2
        assert _row_count(db_conn, "silver.repo_dependency") == 2

    def test_idempotent_second_load(self, db_conn):
        _insert_bronze_repo(db_conn, "acme", "demo", _RAW_DATA)

        load_repo_dependencies(conn=db_conn)
        db_conn.commit()
        load_repo_dependencies(conn=db_conn)
        db_conn.commit()

        assert _row_count(db_conn, "silver.repo_dependency") == 2

    def test_removed_dependency_is_deleted_on_reload(self, db_conn):
        _insert_bronze_repo(db_conn, "acme", "demo", _RAW_DATA)
        load_repo_dependencies(conn=db_conn)
        db_conn.commit()

        shrunk = json.loads(json.dumps(_RAW_DATA))
        shrunk["data"]["repository"]["pyproject_toml"]["text"] = (
            '[project]\ndependencies = ["httpx>=0.28"]\n'
        )
        _insert_bronze_repo(db_conn, "acme", "demo", shrunk)
        load_repo_dependencies(conn=db_conn)
        db_conn.commit()

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT package_name FROM silver.repo_dependency "
                "WHERE repo_owner = 'acme' AND repo_name = 'demo'"
            )
            names = {row[0] for row in cur.fetchall()}
        assert names == {"httpx"}

    def test_empty_bronze_table_returns_zero(self, db_conn):
        with db_conn.cursor() as cur:
            cur.execute("DELETE FROM bronze.github_repos")
        db_conn.commit()

        count = load_repo_dependencies(conn=db_conn)
        assert count == 0
