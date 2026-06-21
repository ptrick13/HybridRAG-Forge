"""Unit tests for loaders/postgres/load_silver.py.

These tests mock psycopg2 and do not require a running database.
They cover get_conn(), own_conn=True branches (commit/rollback/close),
per-repo exception handling, and dependency-count correctness.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from loaders.postgres.load_silver import _blob_text, get_conn, load_repo_dependencies


class TestGetConn:
    def test_uses_env_vars(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "myhost")
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        monkeypatch.setenv("POSTGRES_DB", "mydb")
        monkeypatch.setenv("POSTGRES_USER", "myuser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
        with patch("loaders.postgres.load_silver.psycopg2.connect") as mock_connect:
            get_conn()
        mock_connect.assert_called_once_with(
            host="myhost", port=5433, dbname="mydb", user="myuser", password="secret"
        )

    def test_uses_defaults_when_env_unset(self, monkeypatch):
        for key in (
            "POSTGRES_HOST",
            "POSTGRES_PORT",
            "POSTGRES_DB",
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
        ):
            monkeypatch.delenv(key, raising=False)
        with patch("loaders.postgres.load_silver.psycopg2.connect") as mock_connect:
            get_conn()
        mock_connect.assert_called_once_with(
            host="localhost", port=5432, dbname="hybridrag_forge", user="forge_user", password=""
        )


class TestBlobText:
    def test_returns_text_when_present(self):
        assert _blob_text({"text": "hello"}) == "hello"

    def test_returns_none_for_none_blob(self):
        assert _blob_text(None) is None


def _make_conn(fetchall_rows):
    """Build a MagicMock connection whose cursor() context manager is stable."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = fetchall_rows
    return conn, cursor


class TestLoadRepoDependenciesOwnConn:
    """Exercises own_conn=True paths (no conn argument passed)."""

    def test_commits_and_closes_on_success(self):
        conn, _cursor = _make_conn([])
        with patch("loaders.postgres.load_silver.get_conn", return_value=conn):
            load_repo_dependencies()
        conn.commit.assert_called_once()
        conn.close.assert_called_once()

    def test_rollbacks_and_closes_on_outer_exception(self):
        conn, _cursor = _make_conn([])
        conn.commit.side_effect = RuntimeError("commit failed")
        with patch("loaders.postgres.load_silver.get_conn", return_value=conn):
            with pytest.raises(RuntimeError):
                load_repo_dependencies()
        conn.rollback.assert_called_once()
        conn.close.assert_called_once()


class TestLoadRepoDependenciesParsing:
    def test_counts_parsed_dependencies_for_each_manifest(self):
        raw_data = {
            "data": {
                "repository": {
                    "pyproject_toml": {
                        "text": '[project]\ndependencies = ["httpx>=0.28", "pydantic==2.13.4"]\n'
                    },
                    "requirements_txt": {"text": "ruff==0.15.17\n"},
                    "setup_py": None,
                }
            }
        }
        conn, _cursor = _make_conn([("acme", "demo", raw_data)])

        count = load_repo_dependencies(conn=conn)

        assert count == 3

    def test_empty_repo_table_returns_zero(self):
        conn, _cursor = _make_conn([])
        count = load_repo_dependencies(conn=conn)
        assert count == 0

    def test_continues_after_bad_repo_row(self):
        """A malformed raw_data value for one repo must not abort the others."""
        good_raw_data = {
            "data": {
                "repository": {
                    "pyproject_toml": None,
                    "requirements_txt": {"text": "httpx==0.28.1\n"},
                    "setup_py": None,
                }
            }
        }
        rows = [
            ("broken", "repo", "not-a-dict"),
            ("acme", "demo", good_raw_data),
        ]
        conn, _cursor = _make_conn(rows)

        count = load_repo_dependencies(conn=conn)

        assert count == 1
