# ADR 0001: Concept and Architecture Decisions

**Date**: 2026-06-13
**Status**: Accepted
**Authors**: Patrick Vorreiter

---

## Context

HybridRAG-Forge is an end-to-end data platform that ingests, transforms, and stores data from the GitHub ecosystem in three specialized stores. This ADR documents the foundational decisions made during the design phase.

---

## Decisions

### 1. Data source: GitHub ecosystem instead of e.g. arXiv

**Decision**: The GitHub GraphQL API is used as the primary data source, supplemented by OpenDigger for historical activity metrics.

**Rationale**: GitHub repositories offer exceptional transformation depth: from a single repo one can extract structured metadata (stars, forks, languages), relationship data (dependencies via `requirements.txt`/`pyproject.toml`, contributor overlap), historical time-series (OpenDigger: monthly activity metrics), and unstructured documentation (READMEs). arXiv papers would provide citation graphs, but very few directly operationalizable relationship and activity metrics. The GitHub ecosystem allows all three stores (Postgres, Neo4j, Qdrant) to be populated meaningfully.

---

### 2. Single core use case: Ecosystem Activity & Relationship Intelligence

**Decision**: One clearly named use case instead of several separate use cases.

**Rationale**: Multiple parallel use cases (e.g. "trend analysis" + "dependency audit" + "doc search" as independent features) would have led to inconsistent data models and poor communicability. A consolidated use case — "How do these tools evolve? How are they related? How do I search their docs?" — is easier to communicate as a portfolio project and forces a coherent Star Schema design. All three questions are answered through the same Bronze/Silver/Gold pipeline.

---

### 3. Star Schema design as the analytical core

**Decision**: The Gold layer in PostgreSQL follows a Star Schema with tables `dim_repo`, `dim_date`, and `fct_repo_metrics`.

**Rationale**: A Star Schema enables simple, performant analytical queries (e.g. "How have stars/PR frequency evolved for repos in the `vector_databases` category over the past 12 months?") without complex joins. The schema is directly usable by Streamlit dashboards and open for future extensions (additional fact tables). Normalized 3NF designs would be suboptimal for OLAP workloads and dashboard rendering.

---

### 4. OpenDigger for historical time-series

**Decision**: OpenDigger (opendigger.x-lab.info) is used for historical activity metrics instead of the GitHub REST API.

**Rationale**: The GitHub REST API only delivers current snapshots (current star count), not historical time-series. OpenDigger provides monthly metrics (stars, forks, issues, PRs, contributor count) as static JSON datasets — without API rate limits. For trend analysis over 12–24 months, OpenDigger is the more practical and cost-effective source. OpenDigger data is updated once or quarterly, which is sufficient for this use case.

---

### 5. Neo4j scoping: dependency graph + capped contributor overlap

**Decision**: The Neo4j graph is limited to two relationship types: `(:Repo)-[:DEPENDS_ON]->(:Repo)` and `(:Repo)-[:CONTRIBUTOR_OVERLAP {count: n}]->(:Repo)`. Contributor lists are capped at the top 100 contributors per repo.

**Rationale**: A full contributor graph (all contributors across all 27 repos) would generate millions of nodes and edges that are barely visualizable and no more useful for the use case. The capped overlap (top-100 contributors per repo) captures the relevant core maintainers and power users who genuinely have cross-tool ecosystem knowledge. Dependencies are parsed from `requirements.txt`, `pyproject.toml`, and `setup.py` of the target repos and only modeled as an edge if the dependency repo is itself in the target list.

---

### 6. Qdrant scoping: chunked READMEs

**Decision**: Qdrant contains exclusively chunked READMEs of the target repos — no full documentation websites or code.

**Rationale**: READMEs are the primary, always-present documentation source for open-source repos. Full-docs crawling (ReadTheDocs, GitHub Pages) would greatly increase scope and is disproportionate for the portfolio context. READMEs provide sufficient signal for semantic similarity search and "what does this tool do?" queries. Chunk size: ~512 tokens with overlap, to minimize context loss at chunk boundaries.

---

### 7. LLM enrichment: one-time, low-cost step

**Decision**: LLM-based repo summaries are generated once (or on significant README changes), not daily. Default model: `gpt-4o-mini`.

**Rationale**: Daily LLM calls for all 27 repos would be unnecessarily expensive at standard API pricing and generate no proportional added value (READMEs rarely change fundamentally). A one-time run with a low-cost model (`gpt-4o-mini`) for short, structured summaries (~100 tokens output per repo) costs less than $0.01 for all 27 repos. The model is configurable via `.env` to allow provider and model changes without code modifications.

---

## Rejected Alternatives

| Alternative | Rejected because |
|---|---|
| arXiv as data source | No direct activity or dependency data, weaker transformation depth |
| MongoDB instead of PostgreSQL | Worse OLAP performance, no native window functions for time-series |
| Pinecone/Weaviate instead of Qdrant | Qdrant is self-hosted, open source, consistent with the Docker Compose setup |
| Daily LLM runs | Disproportionate cost without proportional added value |
| Full contributor graphs | Too many nodes, poor visualizability, no clear added value |
