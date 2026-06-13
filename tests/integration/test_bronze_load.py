"""Integration tests for loaders/postgres/load_bronze.py.

Requires Docker. Each test spins up a throw-away PostgreSQL container via
testcontainers, initialises the bronze schema, then asserts correct behaviour
including idempotency (two loads of the same data produce no duplicate rows).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import psycopg2
import pytest

SCHEMA_SQL = Path(__file__).parent.parent.parent / "scripts" / "init_bronze_schema.sql"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_psycopg2_conn(pg):
    """Return a psycopg2 connection to a testcontainers PostgresContainer."""
    url = pg.get_connection_url()
    # testcontainers returns a SQLAlchemy URL; strip the driver specifier.
    dsn = url.replace("postgresql+psycopg2://", "postgresql://", 1)
    return psycopg2.connect(dsn)


def _row_count(conn, table: str) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
        return cur.fetchone()[0]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg():
    """Start a PostgreSQL container and initialise the bronze schema once."""
    pytest.importorskip("testcontainers", reason="testcontainers not installed")
    from testcontainers.postgres import PostgresContainer

    if shutil.which("docker") is None:
        pytest.skip("Docker not available")

    with PostgresContainer("postgres:16-alpine") as container:
        conn = _make_psycopg2_conn(container)
        try:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL.read_text())
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


# ---------------------------------------------------------------------------
# Fixtures: sample JSON files
# ---------------------------------------------------------------------------

_GH_PAYLOAD = {
    "fetched_at": "2024-01-01T00:00:00+00:00",
    "owner": "qdrant",
    "repo": "qdrant",
    "data": {"stargazerCount": 1234},
}

_OD_PAYLOAD = {"2023-01": 42.0, "2023-02": 43.5}


@pytest.fixture
def github_dir(tmp_path) -> Path:
    d = tmp_path / "github_repos"
    d.mkdir()
    (d / "qdrant_qdrant.json").write_text(json.dumps(_GH_PAYLOAD))
    return d


@pytest.fixture
def opendigger_dir(tmp_path) -> Path:
    d = tmp_path / "opendigger"
    d.mkdir()
    (d / "qdrant_qdrant_openrank.json").write_text(json.dumps(_OD_PAYLOAD))
    return d


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLoadGithubRepos:
    def test_inserts_row(self, db_conn, github_dir):
        from loaders.postgres.load_bronze import load_github_repos

        count = load_github_repos(bronze_dir=github_dir, conn=db_conn)
        db_conn.commit()

        assert count == 1
        assert _row_count(db_conn, "bronze.github_repos") == 1

    def test_idempotent_second_load(self, db_conn, github_dir):
        """Loading the same file twice must not create duplicate rows."""
        from loaders.postgres.load_bronze import load_github_repos

        load_github_repos(bronze_dir=github_dir, conn=db_conn)
        db_conn.commit()
        load_github_repos(bronze_dir=github_dir, conn=db_conn)
        db_conn.commit()

        assert _row_count(db_conn, "bronze.github_repos") == 1

    def test_upsert_updates_raw_data(self, db_conn, github_dir):
        """Second load with changed payload must update the existing row."""
        from loaders.postgres.load_bronze import load_github_repos

        load_github_repos(bronze_dir=github_dir, conn=db_conn)
        db_conn.commit()

        updated = {**_GH_PAYLOAD, "data": {"stargazerCount": 9999}}
        (github_dir / "qdrant_qdrant.json").write_text(json.dumps(updated))
        load_github_repos(bronze_dir=github_dir, conn=db_conn)
        db_conn.commit()

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT raw_data->'data'->>'stargazerCount' "
                "FROM bronze.github_repos WHERE repo_owner = 'qdrant'"
            )
            value = cur.fetchone()[0]
        assert value == "9999"
        assert _row_count(db_conn, "bronze.github_repos") == 1

    def test_empty_dir_returns_zero(self, db_conn, tmp_path):
        from loaders.postgres.load_bronze import load_github_repos

        empty = tmp_path / "empty_gh"
        empty.mkdir()
        count = load_github_repos(bronze_dir=empty, conn=db_conn)
        assert count == 0


class TestLoadOpendiggerMetrics:
    def test_inserts_row(self, db_conn, opendigger_dir):
        from loaders.postgres.load_bronze import load_opendigger_metrics

        count = load_opendigger_metrics(bronze_dir=opendigger_dir, conn=db_conn)
        db_conn.commit()

        assert count == 1
        assert _row_count(db_conn, "bronze.opendigger_metrics") == 1

    def test_idempotent_second_load(self, db_conn, opendigger_dir):
        from loaders.postgres.load_bronze import load_opendigger_metrics

        load_opendigger_metrics(bronze_dir=opendigger_dir, conn=db_conn)
        db_conn.commit()
        load_opendigger_metrics(bronze_dir=opendigger_dir, conn=db_conn)
        db_conn.commit()

        assert _row_count(db_conn, "bronze.opendigger_metrics") == 1

    def test_metric_name_stored_correctly(self, db_conn, opendigger_dir):
        from loaders.postgres.load_bronze import load_opendigger_metrics

        load_opendigger_metrics(bronze_dir=opendigger_dir, conn=db_conn)
        db_conn.commit()

        with db_conn.cursor() as cur:
            cur.execute(
                "SELECT metric_name FROM bronze.opendigger_metrics "
                "WHERE repo_owner = 'qdrant' AND repo_name = 'qdrant'"
            )
            metric = cur.fetchone()[0]
        assert metric == "openrank"

    def test_unknown_metric_filename_skipped(self, db_conn, tmp_path):
        from loaders.postgres.load_bronze import load_opendigger_metrics

        d = tmp_path / "od_bad"
        d.mkdir()
        (d / "qdrant_qdrant_unknown_metric.json").write_text(json.dumps({}))
        count = load_opendigger_metrics(bronze_dir=d, conn=db_conn)
        assert count == 0

    def test_multiple_metrics_same_repo(self, db_conn, tmp_path):
        from loaders.postgres.load_bronze import load_opendigger_metrics

        d = tmp_path / "od_multi"
        d.mkdir()
        for metric in ("openrank", "stars", "forks"):
            (d / f"qdrant_qdrant_{metric}.json").write_text(json.dumps({"x": 1}))

        count = load_opendigger_metrics(bronze_dir=d, conn=db_conn)
        db_conn.commit()

        assert count == 3
        assert _row_count(db_conn, "bronze.opendigger_metrics") == 3
