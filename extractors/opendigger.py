import json
import logging
from pathlib import Path

import httpx
import yaml

logger = logging.getLogger(__name__)

BASE_URL = "https://oss.open-digger.cn/github"
BRONZE_DIR = Path("data/bronze/opendigger")
METRICS = [
    "openrank",
    "stars",
    "forks",
    "issues_new",
    "issues_closed",
    "participants",
]


def build_metric_url(owner: str, repo: str, metric: str) -> str:
    return f"{BASE_URL}/{owner}/{repo}/{metric}.json"


def fetch_metric(client: httpx.Client, owner: str, repo: str, metric: str) -> dict | None:
    url = build_metric_url(owner, repo, metric)
    try:
        response = client.get(url, timeout=30)
    except httpx.RequestError:
        logger.exception("Request error fetching %s", url)
        return None

    if response.status_code == 404:
        logger.info("No data available for %s/%s metric=%s (404)", owner, repo, metric)
        return None

    response.raise_for_status()
    return response.json()


def save_metric(
    owner: str,
    repo: str,
    metric: str,
    data: dict,
    bronze_dir: Path = BRONZE_DIR,
) -> Path:
    bronze_dir.mkdir(parents=True, exist_ok=True)
    out = bronze_dir / f"{owner}_{repo}_{metric}.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
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
    with httpx.Client(timeout=30) as client:
        for repo_slug in repos:
            owner, repo = repo_slug.split("/", 1)
            for metric in METRICS:
                try:
                    logger.info("Fetching OpenDigger %s/%s metric=%s", owner, repo, metric)
                    data = fetch_metric(client, owner, repo, metric)
                    if data is not None:
                        save_metric(owner, repo, metric, data)
                except Exception:
                    logger.exception(
                        "Failed to fetch OpenDigger %s/%s metric=%s", owner, repo, metric
                    )
