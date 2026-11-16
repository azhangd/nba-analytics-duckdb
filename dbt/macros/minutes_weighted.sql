{#- Average of a per-game rate (usage, ratings) weighted by minutes played, so a
    two-minute stint doesn't count as much as a full game. Pass `over` to use it
    as a window. -#}
{% macro minutes_weighted(column, minutes='minutes', over=none) -%}
{%- set window = ' OVER ' ~ over if over else '' -%}
SUM({{ column }} * {{ minutes }}){{ window }}
    / NULLIF(SUM(CASE WHEN {{ column }} IS NOT NULL THEN {{ minutes }} END){{ window }}, 0)
{%- endmacro %}
