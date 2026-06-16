"""Unit tests for loaders/postgres/load_bronze.py.

These tests mock psycopg2 and do not require a running database.
They cover the paths that integration tests miss: get_conn(), own_conn=True
branches (commit/rollback/close), per-file exception handlers, and load_all().
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from loaders.postgres.load_bronze import (
    get_conn,
    load_all,
    load_github_repos,
    load_opendigger_metrics,
)


class TestGetConn:
    def test_uses_env_vars(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_HOST", "myhost")
        monkeypatch.setenv("POSTGRES_PORT", "5433")
        monkeypatch.setenv("POSTGRES_DB", "mydb")
        monkeypatch.setenv("POSTGRES_USER", "myuser")
        monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
        with patch("loaders.postgres.load_bronze.psycopg2.connect") as mock_connect:
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
        with patch("loaders.postgres.load_bronze.psycopg2.connect") as mock_connect:
            get_conn()
        mock_connect.assert_called_once_with(
            host="localhost", port=5432, dbname="hybridrag_forge", user="forge_user", password=""
        )


class TestLoadGithubReposOwnConn:
    """Exercises own_conn=True paths (no conn argument passed)."""

    def _write_file(self, tmp_path):
        payload = {"owner": "qdrant", "repo": "qdrant", "fetched_at": "2024-01-01T00:00:00+00:00"}
        (tmp_path / "qdrant_qdrant.json").write_text(json.dumps(payload))

    def test_commits_and_closes_on_success(self, tmp_path):
        self._write_file(tmp_path)
        mock_conn = MagicMock()
        with patch("loaders.postgres.load_bronze.get_conn", return_value=mock_conn):
            load_github_repos(bronze_dir=tmp_path)
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_rollbacks_and_closes_on_outer_exception(self, tmp_path):
        self._write_file(tmp_path)
        mock_conn = MagicMock()
        mock_conn.commit.side_effect = RuntimeError("commit failed")
        with patch("loaders.postgres.load_bronze.get_conn", return_value=mock_conn):
            with pytest.raises(RuntimeError):
                load_github_repos(bronze_dir=tmp_path)
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()


class TestLoadGithubReposInnerException:
    def test_continues_after_bad_json_file(self, tmp_path):
        (tmp_path / "a_bad.json").write_text("not valid json{")
        good = {"owner": "qdrant", "repo": "qdrant", "fetched_at": "2024-01-01"}
        (tmp_path / "z_qdrant_qdrant.json").write_text(json.dumps(good))
        mock_conn = MagicMock()
        count = load_github_repos(bronze_dir=tmp_path, conn=mock_conn)
        assert count == 1


class TestLoadOpendiggerMetricsOwnConn:
    """Exercises own_conn=True paths (no conn argument passed)."""

    def _write_file(self, tmp_path):
        (tmp_path / "qdrant_qdrant_openrank.json").write_text(json.dumps({"2024-01": 1.0}))

    def test_commits_and_closes_on_success(self, tmp_path):
        self._write_file(tmp_path)
        mock_conn = MagicMock()
        with patch("loaders.postgres.load_bronze.get_conn", return_value=mock_conn):
            load_opendigger_metrics(bronze_dir=tmp_path)
        mock_conn.commit.assert_called_once()
        mock_conn.close.assert_called_once()

    def test_rollbacks_and_closes_on_outer_exception(self, tmp_path):
        self._write_file(tmp_path)
        mock_conn = MagicMock()
        mock_conn.commit.side_effect = RuntimeError("commit failed")
        with patch("loaders.postgres.load_bronze.get_conn", return_value=mock_conn):
            with pytest.raises(RuntimeError):
                load_opendigger_metrics(bronze_dir=tmp_path)
        mock_conn.rollback.assert_called_once()
        mock_conn.close.assert_called_once()


class TestLoadOpendiggerMetricsInnerException:
    def test_continues_after_bad_json_file(self, tmp_path):
        (tmp_path / "qdrant_qdrant_openrank.json").write_text("not valid json{")
        mock_conn = MagicMock()
        count = load_opendigger_metrics(bronze_dir=tmp_path, conn=mock_conn)
        assert count == 0


class TestLoadAll:
    def test_calls_both_loaders(self):
        with (
            patch("loaders.postgres.load_bronze.load_github_repos") as mock_gh,
            patch("loaders.postgres.load_bronze.load_opendigger_metrics") as mock_od,
        ):
            load_all()
        mock_gh.assert_called_once_with()
        mock_od.assert_called_once_with()
