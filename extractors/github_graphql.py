import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv()

logger = logging.getLogger(__name__)

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"
BRONZE_DIR = Path("data/bronze/github_repos")

GRAPHQL_QUERY = """
query RepoData($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    name
    description
    stargazerCount
    forkCount
    createdAt
    pushedAt
    primaryLanguage {
      name
    }
    languages(first: 10) {
      edges {
        size
        node {
          name
        }
      }
    }
    repositoryTopics(first: 10) {
      nodes {
        topic {
          name
        }
      }
    }
    licenseInfo {
      spdxId
    }
    pyproject_toml: object(expression: "HEAD:pyproject.toml") {
      ... on Blob {
        text
      }
    }
    requirements_txt: object(expression: "HEAD:requirements.txt") {
      ... on Blob {
        text
      }
    }
    setup_py: object(expression: "HEAD:setup.py") {
      ... on Blob {
        text
      }
    }
    readme: object(expression: "HEAD:README.md") {
      ... on Blob {
        text
      }
    }
  }
}
"""


class RateLimitError(Exception):
    pass


def build_request_payload(owner: str, name: str) -> dict:
    return {
        "query": GRAPHQL_QUERY,
        "variables": {"owner": owner, "name": name},
    }


def _make_request(client: httpx.Client, owner: str, name: str) -> httpx.Response:
    payload = build_request_payload(owner, name)
    response = client.post(GITHUB_GRAPHQL_URL, json=payload)
    if response.status_code in (403, 429):
        remaining = response.headers.get("X-RateLimit-Remaining", "unknown")
        reset = response.headers.get("X-RateLimit-Reset", "unknown")
        logger.warning(
            "Rate limit for %s/%s: status=%s remaining=%s reset=%s",
            owner,
            name,
            response.status_code,
            remaining,
            reset,
        )
        raise RateLimitError(f"Rate limit: {response.status_code}")
    response.raise_for_status()
    return response


@retry(
    retry=retry_if_exception_type(RateLimitError),
    wait=wait_exponential(multiplier=2, min=4, max=120),
    stop=stop_after_attempt(5),
    reraise=True,
)
def _fetch_with_retry(client: httpx.Client, owner: str, name: str) -> httpx.Response:
    return _make_request(client, owner, name)


def fetch_repo(client: httpx.Client, owner: str, name: str) -> dict:
    response = _fetch_with_retry(client, owner, name)
    data = response.json()
    if "errors" in data:
        logger.error("GraphQL errors for %s/%s: %s", owner, name, data["errors"])
    return data


def save_repo(owner: str, name: str, data: dict, bronze_dir: Path = BRONZE_DIR) -> Path:
    bronze_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(UTC).isoformat(),
        "owner": owner,
        "repo": name,
        **data,
    }
    out = bronze_dir / f"{owner}_{name}.json"
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    logger.info("Saved %s", out)
    return out


def load_repos_from_yaml(yaml_path: Path) -> list[str]:
    with yaml_path.open() as f:
        config = yaml.safe_load(f)
    repos: list[str] = []
    for category in config.get("target_repos", {}).values():
        repos.extend(category)
    return repos


def extract_all(repos: list[str]) -> None:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise OSError("GITHUB_TOKEN is not set")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    with httpx.Client(headers=headers, timeout=30) as client:
        for repo_slug in repos:
            owner, name = repo_slug.split("/", 1)
            try:
                logger.info("Fetching %s/%s", owner, name)
                data = fetch_repo(client, owner, name)
                save_repo(owner, name, data)
            except Exception:
                logger.exception("Failed to fetch %s/%s", owner, name)
