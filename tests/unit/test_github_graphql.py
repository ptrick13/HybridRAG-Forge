import json
from unittest.mock import MagicMock, patch

import pytest

from extractors.github_graphql import (
    GRAPHQL_QUERY,
    RateLimitError,
    _make_request,
    build_request_payload,
    extract_all,
    fetch_repo,
    load_repos_from_yaml,
    save_repo,
)


class TestBuildRequestPayload:
    def test_returns_query_and_variables(self):
        payload = build_request_payload("qdrant", "qdrant")
        assert "query" in payload
        assert "variables" in payload

    def test_variables_match_owner_and_name(self):
        payload = build_request_payload("langchain-ai", "langchain")
        assert payload["variables"] == {"owner": "langchain-ai", "name": "langchain"}

    def test_query_is_graphql_string(self):
        payload = build_request_payload("qdrant", "qdrant")
        assert payload["query"] is GRAPHQL_QUERY


class TestGraphQLQueryFields:
    def test_contains_scalar_fields(self):
        for field in ("stargazerCount", "forkCount", "createdAt", "pushedAt", "description"):
            assert field in GRAPHQL_QUERY

    def test_contains_primary_language(self):
        assert "primaryLanguage" in GRAPHQL_QUERY

    def test_contains_languages_with_edges(self):
        assert "languages(first: 10)" in GRAPHQL_QUERY
        assert "edges" in GRAPHQL_QUERY
        assert "size" in GRAPHQL_QUERY

    def test_contains_repository_topics(self):
        assert "repositoryTopics(first: 10)" in GRAPHQL_QUERY

    def test_contains_license_info(self):
        assert "licenseInfo" in GRAPHQL_QUERY
        assert "spdxId" in GRAPHQL_QUERY

    def test_contains_dependency_manifests(self):
        assert "pyproject_toml" in GRAPHQL_QUERY
        assert "requirements_txt" in GRAPHQL_QUERY
        assert "setup_py" in GRAPHQL_QUERY

    def test_contains_readme(self):
        assert 'readme: object(expression: "HEAD:README.md")' in GRAPHQL_QUERY

    def test_dependency_paths_use_head_expression(self):
        assert '"HEAD:pyproject.toml"' in GRAPHQL_QUERY
        assert '"HEAD:requirements.txt"' in GRAPHQL_QUERY
        assert '"HEAD:setup.py"' in GRAPHQL_QUERY


class TestMakeRequest:
    def _mock_response(self, status_code: int, headers: dict | None = None) -> MagicMock:
        response = MagicMock()
        response.status_code = status_code
        response.headers = headers or {}
        return response

    def test_raises_rate_limit_error_on_429(self):
        client = MagicMock()
        client.post.return_value = self._mock_response(
            429, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1234567890"}
        )
        with pytest.raises(RateLimitError):
            _make_request(client, "qdrant", "qdrant")

    def test_raises_rate_limit_error_on_403(self):
        client = MagicMock()
        client.post.return_value = self._mock_response(403)
        with pytest.raises(RateLimitError):
            _make_request(client, "qdrant", "qdrant")

    def test_returns_response_on_200(self):
        client = MagicMock()
        response = self._mock_response(200)
        client.post.return_value = response
        result = _make_request(client, "qdrant", "qdrant")
        assert result is response

    def test_posts_to_graphql_endpoint(self):
        from extractors.github_graphql import GITHUB_GRAPHQL_URL

        client = MagicMock()
        client.post.return_value = self._mock_response(200)
        _make_request(client, "qdrant", "qdrant")
        call_kwargs = client.post.call_args
        assert call_kwargs[0][0] == GITHUB_GRAPHQL_URL


class TestFetchRepo:
    def test_returns_json_on_success(self):
        expected = {"data": {"repository": {"name": "qdrant", "stargazerCount": 100}}}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = expected

        client = MagicMock()
        client.post.return_value = mock_response

        result = fetch_repo(client, "qdrant", "qdrant")
        assert result == expected

    def test_logs_graphql_errors(self, caplog):
        payload = {"data": None, "errors": [{"message": "Could not resolve to a Repository"}]}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = payload

        client = MagicMock()
        client.post.return_value = mock_response

        import logging

        with caplog.at_level(logging.ERROR, logger="extractors.github_graphql"):
            fetch_repo(client, "qdrant", "qdrant")

        assert any("GraphQL errors" in r.message for r in caplog.records)


class TestSaveRepo:
    def test_writes_json_file(self, tmp_path):
        data = {"data": {"repository": {"name": "qdrant"}}}
        out = save_repo("qdrant", "qdrant", data, bronze_dir=tmp_path)
        assert out.exists()
        saved = json.loads(out.read_text())
        assert saved["owner"] == "qdrant"
        assert saved["repo"] == "qdrant"
        assert "fetched_at" in saved

    def test_filename_uses_owner_repo(self, tmp_path):
        out = save_repo("langchain-ai", "langchain", {}, bronze_dir=tmp_path)
        assert out.name == "langchain-ai_langchain.json"

    def test_creates_parent_dirs(self, tmp_path):
        nested = tmp_path / "a" / "b"
        save_repo("x", "y", {}, bronze_dir=nested)
        assert nested.exists()


class TestLoadReposFromYaml:
    def test_returns_flattened_list(self, tmp_path):
        yaml_file = tmp_path / "repos.yaml"
        yaml_file.write_text(
            "target_repos:\n"
            "  vector_dbs:\n"
            "    - qdrant/qdrant\n"
            "    - weaviate/weaviate\n"
            "  llm_frameworks:\n"
            "    - langchain-ai/langchain\n"
        )
        result = load_repos_from_yaml(yaml_file)
        assert result == ["qdrant/qdrant", "weaviate/weaviate", "langchain-ai/langchain"]

    def test_missing_target_repos_key_returns_empty(self, tmp_path):
        yaml_file = tmp_path / "repos.yaml"
        yaml_file.write_text("other_key:\n  - value\n")
        assert load_repos_from_yaml(yaml_file) == []

    def test_empty_target_repos_returns_empty(self, tmp_path):
        yaml_file = tmp_path / "repos.yaml"
        yaml_file.write_text("target_repos: {}\n")
        assert load_repos_from_yaml(yaml_file) == []

    def test_single_category(self, tmp_path):
        yaml_file = tmp_path / "repos.yaml"
        yaml_file.write_text("target_repos:\n  all:\n    - owner/repo\n")
        assert load_repos_from_yaml(yaml_file) == ["owner/repo"]


class TestExtractAll:
    def test_raises_when_token_missing(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(OSError, match="GITHUB_TOKEN"):
            extract_all(["qdrant/qdrant"])

    def test_creates_client_with_bearer_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
        mock_client = MagicMock()
        with (
            patch("extractors.github_graphql.httpx.Client") as mock_cls,
            patch("extractors.github_graphql.fetch_repo", return_value={}),
            patch("extractors.github_graphql.save_repo"),
        ):
            mock_cls.return_value.__enter__.return_value = mock_client
            extract_all(["qdrant/qdrant"])
        assert mock_cls.call_args.kwargs["headers"]["Authorization"] == "Bearer secret-token"

    def test_calls_fetch_and_save_for_each_repo(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        mock_client = MagicMock()
        with (
            patch("extractors.github_graphql.httpx.Client") as mock_cls,
            patch("extractors.github_graphql.fetch_repo", return_value={"data": {}}) as mock_fetch,
            patch("extractors.github_graphql.save_repo") as mock_save,
        ):
            mock_cls.return_value.__enter__.return_value = mock_client
            extract_all(["qdrant/qdrant", "langchain-ai/langchain"])
        assert mock_fetch.call_count == 2
        assert mock_save.call_count == 2

    def test_passes_owner_and_name_to_fetch(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        mock_client = MagicMock()
        with (
            patch("extractors.github_graphql.httpx.Client") as mock_cls,
            patch("extractors.github_graphql.fetch_repo", return_value={}) as mock_fetch,
            patch("extractors.github_graphql.save_repo"),
        ):
            mock_cls.return_value.__enter__.return_value = mock_client
            extract_all(["langchain-ai/langchain"])
        args = mock_fetch.call_args[0]
        assert args[1] == "langchain-ai"
        assert args[2] == "langchain"

    def test_continues_after_exception(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "tok")
        mock_client = MagicMock()
        with (
            patch("extractors.github_graphql.httpx.Client") as mock_cls,
            patch("extractors.github_graphql.fetch_repo", side_effect=RuntimeError("boom")),
            patch("extractors.github_graphql.save_repo") as mock_save,
        ):
            mock_cls.return_value.__enter__.return_value = mock_client
            extract_all(["bad/repo", "another/bad"])  # must not raise
        mock_save.assert_not_called()
