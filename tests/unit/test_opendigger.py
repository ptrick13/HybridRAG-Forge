import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from extractors.opendigger import (
    BASE_URL,
    METRICS,
    build_metric_url,
    fetch_metric,
    save_metric,
)


class TestBuildMetricUrl:
    def test_url_structure(self):
        url = build_metric_url("qdrant", "qdrant", "openrank")
        assert url == f"{BASE_URL}/qdrant/qdrant/openrank.json"

    def test_url_contains_owner_repo_metric(self):
        url = build_metric_url("langchain-ai", "langchain", "stars")
        assert "langchain-ai" in url
        assert "langchain" in url
        assert "stars" in url
        assert url.endswith(".json")

    def test_all_metrics_build_valid_url(self):
        for metric in METRICS:
            url = build_metric_url("test-owner", "test-repo", metric)
            assert url.startswith("https://")
            assert metric in url


class TestFetchMetric:
    def _make_client(self, status_code: int, body: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        if body is not None:
            response.json.return_value = body
        client = MagicMock()
        client.get.return_value = response
        return client

    def test_returns_none_on_404(self):
        client = self._make_client(404)
        result = fetch_metric(client, "qdrant", "qdrant", "openrank")
        assert result is None

    def test_does_not_raise_on_404(self):
        client = self._make_client(404)
        fetch_metric(client, "nonexistent", "repo", "openrank")

    def test_logs_info_on_404(self, caplog):
        import logging

        client = self._make_client(404)
        with caplog.at_level(logging.INFO, logger="extractors.opendigger"):
            fetch_metric(client, "some-owner", "some-repo", "stars")
        assert any("404" in r.message or "No data" in r.message for r in caplog.records)

    def test_returns_data_on_200(self):
        data = {"2024-01": 42.0, "2024-02": 45.0}
        client = self._make_client(200, data)
        result = fetch_metric(client, "qdrant", "qdrant", "openrank")
        assert result == data

    def test_calls_correct_url(self):
        client = self._make_client(200, {})
        fetch_metric(client, "qdrant", "qdrant", "forks")
        expected_url = build_metric_url("qdrant", "qdrant", "forks")
        client.get.assert_called_once_with(expected_url, timeout=30)

    def test_returns_none_on_request_error(self):
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("connection refused")
        result = fetch_metric(client, "qdrant", "qdrant", "openrank")
        assert result is None


class TestSaveMetric:
    def test_writes_json_file(self, tmp_path):
        data = {"2024-01": 10.5}
        out = save_metric("qdrant", "qdrant", "openrank", data, bronze_dir=tmp_path)
        assert out.exists()
        saved = json.loads(out.read_text())
        assert saved == data

    def test_filename_convention(self, tmp_path):
        out = save_metric("langchain-ai", "langchain", "stars", {}, bronze_dir=tmp_path)
        assert out.name == "langchain-ai_langchain_stars.json"

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "deep" / "nested"
        save_metric("x", "y", "forks", {}, bronze_dir=nested)
        assert nested.exists()
