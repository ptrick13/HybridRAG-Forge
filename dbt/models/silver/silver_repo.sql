-- Silver: one normalized row per repo, deduped by latest fetch.
-- Bot-filtering is intentionally out of scope here — it requires contributor
-- data that only enters the platform in Phase 6 (Neo4j contributor overlap).

with bronze_repos as (

    select
        repo_owner,
        repo_name,
        fetched_at,
        raw_data -> 'data' -> 'repository' as repo,
        row_number() over (
            partition by repo_owner, repo_name
            order by fetched_at desc
        ) as rn
    from {{ source('bronze', 'github_repos') }}

),

deduped as (

    select repo_owner, repo_name, fetched_at, repo
    from bronze_repos
    where rn = 1

)

select
    repo_owner || '/' || repo_name as repo_id,
    repo_owner,
    repo_name,
    repo ->> 'name' as name,
    repo ->> 'description' as description,
    (repo ->> 'stargazerCount')::bigint as stargazer_count,
    (repo ->> 'forkCount')::bigint as fork_count,
    (repo ->> 'createdAt')::timestamptz as created_at,
    (repo ->> 'pushedAt')::timestamptz as pushed_at,
    lower(repo -> 'primaryLanguage' ->> 'name') as primary_language,
    repo -> 'licenseInfo' ->> 'spdxId' as license_spdx,
    (
        select array_agg(distinct lower(topic -> 'topic' ->> 'name'))
        from jsonb_array_elements(
            coalesce(repo -> 'repositoryTopics' -> 'nodes', '[]'::jsonb)
        ) as topic
    ) as topics,
    (
        select jsonb_agg(
            jsonb_build_object('name', lang_name, 'size', lang_size)
            order by lang_size desc
        )
        from (
            select
                edge -> 'node' ->> 'name' as lang_name,
                (edge ->> 'size')::bigint as lang_size
            from jsonb_array_elements(
                coalesce(repo -> 'languages' -> 'edges', '[]'::jsonb)
            ) as edge
        ) as langs
    ) as languages,
    fetched_at
from deduped
