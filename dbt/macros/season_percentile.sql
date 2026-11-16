{#- Percentile (0-100) of a value among non-NULL values in the same season; NULL stays NULL.
    PERCENT_RANK alone ranks NULLs as the highest values. -#}
{% macro season_percentile(column, season='season', descending=false) -%}
CASE WHEN ({{ column }}) IS NOT NULL THEN
    (PERCENT_RANK() OVER (
        PARTITION BY {{ season }}, ({{ column }}) IS NULL
        ORDER BY ({{ column }}){% if descending %} DESC{% endif %}
    ) * 100)::INT
END
{%- endmacro %}
