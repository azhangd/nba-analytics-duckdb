{# bronze.schedule stores dates as 'MM/DD/YYYY HH:MM:SS' text, which sorts January before October. #}
{% macro parse_game_date(column) -%}
    CAST(strptime({{ column }}, '%m/%d/%Y %H:%M:%S') AS DATE)
{%- endmacro %}
