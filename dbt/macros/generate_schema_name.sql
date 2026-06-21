{#
    dbt's default behaviour prefixes a model's custom schema with the target
    schema (e.g. "public" + "silver" -> "public_silver"). That would split the
    Medallion layers across two physical schemas: silver.repo_dependency
    (written directly by loaders/postgres/load_silver.py) and
    public_silver.silver_repo (the dbt model). This override makes the custom
    schema authoritative so both land in the literal "silver" schema.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
