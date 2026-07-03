{{ config(materialized='table', schema='gold', alias='player_season_on_off_stats', tags=['gold']) }}

WITH stints AS (
    SELECT
        lineups.team_id,
        games.season,
        CAST(lineups.player_ids_str AS TEXT) AS player_ids_str,
        CAST(lineups.duration_seconds AS DOUBLE) / 60.0 AS minutes,
        CAST(COALESCE(lineups.points_for, 0) AS DOUBLE) AS points_for,
        CAST(COALESCE(lineups.points_against, 0) AS DOUBLE) AS points_against
    FROM {{ ref('fct_lineups') }} AS lineups
    JOIN {{ ref('fct_games') }} AS games
        ON lineups.game_id = games.game_id
    WHERE lineups.player_count >= 5
      AND lineups.duration_seconds > 0
      AND games.game_type = 'regular_season'
),
active_stints AS (
    SELECT
        stints.team_id,
        stints.season,
        TRY_CAST(token AS INTEGER) AS player_id,
        stints.minutes,
        stints.points_for,
        stints.points_against
    FROM stints,
    unnest(
        regexp_split_to_array(
            regexp_replace(TRIM(BOTH '-,' FROM stints.player_ids_str), '-', ',', 'g'),
            ','
        )
    ) AS split(token)
    WHERE token <> ''
),
team_totals AS (
    SELECT
        team_id,
        season,
        SUM(minutes) AS total_minutes,
        SUM(points_for) AS total_points_for,
        SUM(points_against) AS total_points_against
    FROM stints
    GROUP BY team_id, season
),
player_on AS (
    SELECT
        player_id,
        team_id,
        season,
        SUM(minutes) AS on_minutes,
        SUM(points_for) AS on_points_for,
        SUM(points_against) AS on_points_against
    FROM active_stints
    WHERE player_id IS NOT NULL
    GROUP BY player_id, team_id, season
),
ratings AS (
    SELECT
        player_on.player_id,
        CAST(players.full_name AS TEXT) AS player_name,
        player_on.team_id,
        player_on.season,
        ROUND(player_on.on_minutes, 1) AS on_minutes,
        ROUND(team_totals.total_minutes - player_on.on_minutes, 1) AS off_minutes,
        CASE
            WHEN player_on.on_minutes > 0
                THEN ROUND(
                    (player_on.on_points_for - player_on.on_points_against)
                    / player_on.on_minutes
                    * 48.0,
                    1
                )
        END AS on_net_rating,
        CASE
            WHEN team_totals.total_minutes - player_on.on_minutes > 0
                THEN ROUND(
                    (
                        (team_totals.total_points_for - player_on.on_points_for)
                        - (team_totals.total_points_against - player_on.on_points_against)
                    )
                    / (team_totals.total_minutes - player_on.on_minutes)
                    * 48.0,
                    1
                )
        END AS off_net_rating,
        CAST(player_on.on_points_for AS INTEGER) AS on_pts_for,
        CAST(player_on.on_points_against AS INTEGER) AS on_pts_against
    FROM player_on
    JOIN team_totals
        ON player_on.team_id = team_totals.team_id
       AND player_on.season = team_totals.season
    LEFT JOIN {{ ref('dim_players') }} AS players
        ON player_on.player_id = players.player_id
)
SELECT
    player_id,
    COALESCE(player_name, 'Player ' || CAST(player_id AS TEXT)) AS player_name,
    team_id,
    season,
    on_minutes,
    off_minutes,
    on_net_rating,
    off_net_rating,
    CASE
        WHEN on_net_rating IS NOT NULL THEN ROUND(on_net_rating - COALESCE(off_net_rating, 0.0), 1)
    END AS on_off_differential,
    on_pts_for,
    on_pts_against
FROM ratings
