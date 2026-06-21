-- Idempotent Silver layer schema initialization.
-- Safe to run multiple times (CREATE ... IF NOT EXISTS throughout).
--
-- silver.repo_dependency is populated directly by loaders/postgres/load_silver.py
-- (not by a dbt model) because dbt-postgres has no Python model support and
-- TOML/setup.py parsing cannot be expressed in SQL. dbt still applies generic
-- tests to it via a source definition in dbt/models/silver/sources.yml.

CREATE SCHEMA IF NOT EXISTS silver;

CREATE TABLE IF NOT EXISTS silver.repo_dependency (
    id              BIGSERIAL,
    repo_owner      TEXT        NOT NULL,
    repo_name       TEXT        NOT NULL,
    source_manifest TEXT        NOT NULL
        CONSTRAINT ck_repo_dependency_source_manifest
        CHECK (source_manifest IN ('pyproject_toml', 'requirements_txt', 'setup_py')),
    package_name    TEXT        NOT NULL,
    loaded_at       TIMESTAMPTZ NOT NULL,
    CONSTRAINT pk_repo_dependency PRIMARY KEY (id),
    CONSTRAINT uq_repo_dependency UNIQUE (repo_owner, repo_name, source_manifest, package_name)
);
