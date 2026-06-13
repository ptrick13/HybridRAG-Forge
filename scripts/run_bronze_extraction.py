#!/usr/bin/env python3
"""Run Bronze-Layer extraction: GitHub GraphQL + OpenDigger for all target repos."""

import argparse
import logging
import sys
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).parent.parent))

import extractors.github_graphql as gh
import extractors.opendigger as od

CONFIG_PATH = Path(__file__).parent.parent / "extractors" / "config" / "target_repos.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bronze extraction: GitHub GraphQL + OpenDigger")
    parser.add_argument(
        "--repos",
        nargs="+",
        metavar="OWNER/REPO",
        help="Limit extraction to these repos (e.g. --repos qdrant/qdrant langchain-ai/langchain)",
    )
    parser.add_argument(
        "--skip-github",
        action="store_true",
        help="Skip GitHub GraphQL extraction",
    )
    parser.add_argument(
        "--skip-opendigger",
        action="store_true",
        help="Skip OpenDigger extraction",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    all_repos = gh.load_repos_from_yaml(CONFIG_PATH)

    if args.repos:
        unknown = set(args.repos) - set(all_repos)
        if unknown:
            logger.warning("Repos not in target_repos.yaml (will still fetch): %s", unknown)
        repos = args.repos
    else:
        repos = all_repos

    logger.info("Starting Bronze extraction for %d repo(s)", len(repos))

    if not args.skip_github:
        logger.info("--- GitHub GraphQL ---")
        gh.extract_all(repos)

    if not args.skip_opendigger:
        logger.info("--- OpenDigger ---")
        od.extract_all(repos)

    logger.info("Bronze extraction complete.")


if __name__ == "__main__":
    main()
