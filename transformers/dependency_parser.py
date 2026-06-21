"""Parse Python dependency manifests fetched into the Bronze layer.

dbt-postgres has no Python model support, so manifest parsing (TOML/AST)
happens here in plain Python before the result is loaded into
``silver.repo_dependency`` by loaders.postgres.load_silver.
"""

from __future__ import annotations

import ast
import logging
import re
import tomllib

logger = logging.getLogger(__name__)

_VERSION_OPERATORS = re.compile(r"===|~=|==|!=|<=|>=|<|>")


def normalize_package_name(name: str) -> str:
    """Normalize a raw dependency spec down to a bare, PEP 503 package name."""
    name = name.split("@", 1)[0]
    name = name.split(";", 1)[0]
    name = name.split("[", 1)[0]
    name = _VERSION_OPERATORS.split(name, maxsplit=1)[0]
    name = name.strip()
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_requirements_txt(text: str | None) -> list[str]:
    """Extract normalized package names from a requirements.txt file."""
    if not text:
        return []

    names: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue

        spec = line.split("@", 1)[0].strip()
        if not spec:
            # "name @ <url>" with nothing meaningful before '@' is a bare URL install.
            continue
        if spec.startswith(("http://", "https://", "git+")):
            continue

        name = normalize_package_name(line)
        if name:
            names.append(name)

    return names


def parse_pyproject_toml(text: str | None) -> list[str]:
    """Extract normalized package names from a pyproject.toml file.

    Supports PEP 621 ``[project.dependencies]`` and Poetry's
    ``[tool.poetry.dependencies]`` table.
    """
    if not text:
        return []

    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        logger.warning("Could not parse pyproject.toml as TOML")
        return []

    names: list[str] = []

    project_deps = data.get("project", {}).get("dependencies", [])
    for dep in project_deps:
        name = normalize_package_name(dep)
        if name:
            names.append(name)

    poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
    for key in poetry_deps:
        if key.lower() == "python":
            continue
        name = normalize_package_name(key)
        if name:
            names.append(name)

    return names


def parse_setup_py(text: str | None) -> list[str]:
    """Extract normalized package names from a setup.py file.

    Only statically determinable ``install_requires=[...]`` literals are
    supported. Anything dynamically computed is intentionally skipped
    rather than executed or guessed at.
    """
    if not text:
        return []

    try:
        tree = ast.parse(text)
    except SyntaxError:
        logger.warning("Could not parse setup.py as Python source")
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "install_requires":
                continue
            try:
                requires = ast.literal_eval(keyword.value)
            except ValueError:
                continue
            if not isinstance(requires, list | tuple):
                continue
            names = [normalize_package_name(r) for r in requires if isinstance(r, str)]
            return [n for n in names if n]

    return []
