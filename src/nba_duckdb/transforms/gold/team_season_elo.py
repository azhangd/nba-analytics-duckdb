"""Pure transforms for transparent Elo ratings and history."""

from __future__ import annotations

import polars as pl

from nba_duckdb.analytics.elo import DEFAULT_ELO, project_record, update_elo

TEAM_SEASON_ELO = (
    "team_id",
    "season",
    "team_abbreviation",
    "comparison_scope",
    "comparison_team_count",
    "elo_rating",
    "current_wins",
    "current_losses",
    "games_played",
    "projected_wins",
    "projected_losses",
    "projected_win_pct",
    "remaining_games",
    "win_pct",
)

TEAM_GAME_ELO_HISTORY = (
    "team_id",
    "season",
    "game_id",
    "game_date",
    "team_abbreviation",
    "opp_team_id",
    "opp_team_abbreviation",
    "is_home",
    "result",
    "margin",
    "elo_before",
    "elo_after",
    "elo_delta",
    "opp_elo_before",
    "opp_elo_after",
)


def team_abbreviations(dim_teams: pl.DataFrame) -> dict[int, str]:
    mapping = {}
    for row in dim_teams.iter_rows(named=True):
        if row.get("team_id") and row.get("abbreviation"):
            mapping[int(row["team_id"])] = str(row["abbreviation"])
    return mapping


def seasons_in_games(games: pl.DataFrame) -> list[str]:
    if games.is_empty() or "season" not in games.columns:
        return []
    return sorted(str(value) for value in games["season"].drop_nulls().unique().to_list())


def build_team_elo_rows(
    silver_games: pl.DataFrame,
    dim_teams: pl.DataFrame,
    *,
    target_seasons: list[str],
) -> tuple[list[dict], list[dict]]:
    if silver_games.is_empty():
        return [], []
    silver_games = silver_games.filter(pl.col("game_id").str.starts_with("002"))
    if "season" in silver_games.columns:
        silver_games = silver_games.filter(pl.col("season").is_in(target_seasons))

    team_abbr_map = team_abbreviations(dim_teams)
    rating_rows = []
    history_rows = []
    for season_value in target_seasons:
        season_games = (
            silver_games.filter(pl.col("season") == season_value)
            if "season" in silver_games.columns
            else silver_games
        )
        if season_games.is_empty():
            continue

        all_team_ids = set()
        for row in season_games.iter_rows(named=True):
            home = row.get("home_team_id")
            away = row.get("away_team_id")
            if home and home in team_abbr_map:
                all_team_ids.add(home)
            if away and away in team_abbr_map:
                all_team_ids.add(away)
        comparison_team_count = len(all_team_ids)
        comparison_scope = "full_league" if comparison_team_count == 30 else "loaded_sample"

        elos: dict[int, float] = {team_id: DEFAULT_ELO for team_id in all_team_ids}
        records: dict[int, dict] = {team_id: {"wins": 0, "losses": 0} for team_id in all_team_ids}
        completed = season_games.filter(pl.col("status") == "Final").sort("game_date")
        for game in completed.iter_rows(named=True):
            home_id = game["home_team_id"]
            away_id = game["away_team_id"]
            home_score = game.get("home_score", 0) or 0
            away_score = game.get("away_score", 0) or 0
            if home_score == 0 and away_score == 0:
                continue
            if home_id not in elos or away_id not in elos:
                continue

            margin = abs(home_score - away_score)
            home_won = home_score > away_score
            home_before = elos[home_id]
            away_before = elos[away_id]
            if home_won:
                new_winner, new_loser = update_elo(
                    elos[home_id], elos[away_id], margin, winner_home=True
                )
                elos[home_id] = new_winner
                elos[away_id] = new_loser
                records[home_id]["wins"] += 1
                records[away_id]["losses"] += 1
            else:
                new_winner, new_loser = update_elo(
                    elos[away_id], elos[home_id], margin, winner_home=False
                )
                elos[away_id] = new_winner
                elos[home_id] = new_loser
                records[away_id]["wins"] += 1
                records[home_id]["losses"] += 1

            home_after = elos[home_id]
            away_after = elos[away_id]
            game_id = game.get("game_id")
            game_date = game.get("game_date")
            for team_id, opp_id, before, after, opp_before, opp_after, is_home in (
                (home_id, away_id, home_before, home_after, away_before, away_after, True),
                (away_id, home_id, away_before, away_after, home_before, home_after, False),
            ):
                won = (is_home and home_won) or (not is_home and not home_won)
                signed_margin = margin if won else -margin
                history_rows.append({
                    "team_id": team_id,
                    "season": season_value,
                    "game_id": game_id,
                    "game_date": game_date,
                    "team_abbreviation": team_abbr_map.get(team_id, ""),
                    "opp_team_id": opp_id,
                    "opp_team_abbreviation": team_abbr_map.get(opp_id, ""),
                    "is_home": is_home,
                    "result": "W" if won else "L",
                    "margin": signed_margin,
                    "elo_before": round(before, 2),
                    "elo_after": round(after, 2),
                    "elo_delta": round(after - before, 2),
                    "opp_elo_before": round(opp_before, 2),
                    "opp_elo_after": round(opp_after, 2),
                })

        scheduled = season_games.filter(pl.col("status") != "Final")
        remaining_by_team: dict[int, list] = {team_id: [] for team_id in all_team_ids}
        for game in scheduled.iter_rows(named=True):
            home_id = game.get("home_team_id")
            away_id = game.get("away_team_id")
            if home_id and home_id in remaining_by_team:
                remaining_by_team[home_id].append({"opponent_id": away_id, "home": True})
            if away_id and away_id in remaining_by_team:
                remaining_by_team[away_id].append({"opponent_id": home_id, "home": False})

        for team_id in sorted(all_team_ids):
            rec = records[team_id]
            if comparison_scope == "full_league":
                projection = project_record(
                    team_elo=elos[team_id],
                    current_wins=rec["wins"],
                    current_losses=rec["losses"],
                    remaining_games=remaining_by_team.get(team_id, []),
                    all_elos=elos,
                )
                projected_wins = projection["projected_wins"]
                projected_losses = projection["projected_losses"]
                projected_win_pct = projection["win_pct"]
            else:
                projection = {"remaining_games": len(remaining_by_team.get(team_id, []))}
                projected_wins = None
                projected_losses = None
                projected_win_pct = None

            games_played = rec["wins"] + rec["losses"]
            win_pct = round(rec["wins"] / games_played, 3) if games_played > 0 else 0.0
            rating_rows.append({
                "team_id": team_id,
                "season": season_value,
                "team_abbreviation": team_abbr_map.get(team_id, ""),
                "comparison_scope": comparison_scope,
                "comparison_team_count": comparison_team_count,
                "elo_rating": round(elos[team_id], 1),
                "current_wins": rec["wins"],
                "current_losses": rec["losses"],
                "games_played": games_played,
                "projected_wins": projected_wins,
                "projected_losses": projected_losses,
                "projected_win_pct": projected_win_pct,
                "remaining_games": projection["remaining_games"],
                "win_pct": win_pct,
            })

    if not rating_rows:
        return [], history_rows
    sorted_rows = (
        pl.DataFrame(rating_rows)
        .sort(["season", "elo_rating"], descending=[False, True])
        .to_dicts()
    )
    return sorted_rows, history_rows
