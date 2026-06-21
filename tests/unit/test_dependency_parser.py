"""Unit tests for transformers/dependency_parser.py."""

from __future__ import annotations

from transformers.dependency_parser import (
    normalize_package_name,
    parse_pyproject_toml,
    parse_requirements_txt,
    parse_setup_py,
)


class TestNormalizePackageName:
    def test_strips_extras(self):
        assert normalize_package_name("requests[security]") == "requests"

    def test_strips_environment_marker(self):
        assert normalize_package_name('pywin32; platform_system=="Windows"') == "pywin32"

    def test_strips_version_operators(self):
        assert normalize_package_name("httpx>=0.28.1") == "httpx"
        assert normalize_package_name("httpx==0.28.1") == "httpx"
        assert normalize_package_name("httpx<=0.28.1") == "httpx"
        assert normalize_package_name("httpx!=0.28.1") == "httpx"
        assert normalize_package_name("httpx~=0.28") == "httpx"
        assert normalize_package_name("httpx===0.28.1") == "httpx"
        assert normalize_package_name("httpx<1") == "httpx"
        assert normalize_package_name("httpx>1") == "httpx"

    def test_strips_url_install(self):
        assert normalize_package_name("name @ git+https://example.com/repo.git") == "name"

    def test_pep503_normalization(self):
        assert normalize_package_name("PyYAML") == "pyyaml"
        assert normalize_package_name("psycopg2_binary") == "psycopg2-binary"
        assert normalize_package_name("Apache.Airflow") == "apache-airflow"


class TestParseRequirementsTxt:
    def test_none_input(self):
        assert parse_requirements_txt(None) == []

    def test_empty_string(self):
        assert parse_requirements_txt("") == []

    def test_basic_pins(self):
        text = "apache-airflow==3.2.2\npsycopg2-binary==2.9.12\n"
        assert parse_requirements_txt(text) == ["apache-airflow", "psycopg2-binary"]

    def test_skips_comments_and_blank_lines(self):
        text = "# a comment\n\nhttpx==0.28.1\n   \n"
        assert parse_requirements_txt(text) == ["httpx"]

    def test_skips_editable_and_recursive_flags(self):
        text = "-e .\n-r requirements-dev.txt\n--index-url https://example.com\nhttpx==0.28.1\n"
        assert parse_requirements_txt(text) == ["httpx"]

    def test_skips_bare_vcs_url(self):
        text = "https://github.com/foo/bar/archive/master.zip\nhttpx==0.28.1\n"
        assert parse_requirements_txt(text) == ["httpx"]

    def test_name_with_vcs_url(self):
        text = "name @ git+https://example.com/repo.git\n"
        assert parse_requirements_txt(text) == ["name"]

    def test_inline_comment(self):
        text = "httpx==0.28.1  # pinned for compat\n"
        assert parse_requirements_txt(text) == ["httpx"]

    def test_skips_line_with_nothing_before_at(self):
        text = "@example\nhttpx==0.28.1\n"
        assert parse_requirements_txt(text) == ["httpx"]


class TestParsePyprojectToml:
    def test_none_input(self):
        assert parse_pyproject_toml(None) == []

    def test_invalid_toml(self):
        assert parse_pyproject_toml("not = valid = toml = [") == []

    def test_neither_style_present(self):
        text = "[build-system]\nrequires = ['hatchling']\n"
        assert parse_pyproject_toml(text) == []

    def test_pep621_style(self):
        text = """
[project]
name = "demo"
dependencies = ["httpx>=0.28", "pydantic==2.13.4"]
"""
        assert parse_pyproject_toml(text) == ["httpx", "pydantic"]

    def test_poetry_style_excludes_python_key(self):
        text = """
[tool.poetry.dependencies]
python = "^3.11"
httpx = "^0.28"
PyYAML = "^6.0"
"""
        assert parse_pyproject_toml(text) == ["httpx", "pyyaml"]


class TestParseSetupPy:
    def test_none_input(self):
        assert parse_setup_py(None) == []

    def test_syntax_error(self):
        assert parse_setup_py("def f(:\n") == []

    def test_no_install_requires(self):
        text = "from setuptools import setup\nsetup(name='demo')\n"
        assert parse_setup_py(text) == []

    def test_literal_install_requires(self):
        text = (
            "from setuptools import setup\n"
            "setup(\n"
            "    name='demo',\n"
            "    install_requires=['httpx>=0.28', 'PyYAML==6.0.3'],\n"
            ")\n"
        )
        assert parse_setup_py(text) == ["httpx", "pyyaml"]

    def test_dynamic_install_requires_is_skipped(self):
        text = (
            "from setuptools import setup\n"
            "deps = open('requirements.txt').read().splitlines()\n"
            "setup(name='demo', install_requires=deps)\n"
        )
        assert parse_setup_py(text) == []

    def test_non_list_install_requires_is_skipped(self):
        text = "from setuptools import setup\nsetup(name='demo', install_requires='httpx')\n"
        assert parse_setup_py(text) == []
