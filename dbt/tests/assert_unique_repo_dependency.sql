-- Singular test: silver.repo_dependency must be unique per
-- (repo_owner, repo_name, source_manifest, package_name).
-- A plain `unique` generic test only covers single columns, and dbt_utils
-- is not a dependency of this project, hence this composite check.

select repo_owner, repo_name, source_manifest, package_name, count(*)
from {{ source('silver', 'repo_dependency') }}
group by repo_owner, repo_name, source_manifest, package_name
having count(*) > 1
