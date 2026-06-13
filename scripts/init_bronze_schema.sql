-- Idempotent Bronze layer schema initialization.
-- Safe to run multiple times (CREATE ... IF NOT EXISTS throughout).

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.github_repos (
    id          BIGSERIAL,
    repo_owner  TEXT        NOT NULL,
    repo_name   TEXT        NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    raw_data    JSONB       NOT NULL,
    CONSTRAINT pk_github_repos   PRIMARY KEY (id),
    CONSTRAINT uq_github_repos   UNIQUE (repo_owner, repo_name)
);

CREATE TABLE IF NOT EXISTS bronze.opendigger_metrics (
    id          BIGSERIAL,
    repo_owner  TEXT        NOT NULL,
    repo_name   TEXT        NOT NULL,
    metric_name TEXT        NOT NULL,
    fetched_at  TIMESTAMPTZ NOT NULL,
    raw_data    JSONB       NOT NULL,
    CONSTRAINT pk_opendigger_metrics PRIMARY KEY (id),
    CONSTRAINT uq_opendigger_metrics UNIQUE (repo_owner, repo_name, metric_name)
);
