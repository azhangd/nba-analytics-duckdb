"""Gold: Compute player embeddings (PCA + UMAP + GMM) and update similarity."""

import json
import logging
import os
from datetime import datetime, timezone

import polars as pl

from nba_duckdb.db import delete_where, insert_rows, read_table, upsert_rows
from nba_duckdb.modeling.player_embeddings import compute_embeddings
from nba_duckdb.season_utils import resolved_target_seasons

logger = logging.getLogger("nba_duckdb.tasks.gold.player_season_embeddings")


def run(**kwargs):
    target_seasons = resolved_target_seasons(
        season=kwargs.get("season"),
        seasons=kwargs.get("seasons"),
        game_ids=[str(game_id) for game_id in kwargs.get("game_ids", []) or []],
        regular_season_only=True,
    )

    season_stats = read_table("gold", "player_season_stats")
    player_shot_profile = read_table("gold", "player_season_shot_profile")

    if season_stats.is_empty():
        logger.warning("No player season stats — cannot compute embeddings")
        return {"status": "skipped"}

    embeddings_rows: list[dict[str, object]] = []
    similarity_rows: list[dict[str, object]] = []
    summary: list[dict[str, object]] = []

    from nba_duckdb.modeling.player_embeddings import ARTIFACT_DIR

    for season_value in target_seasons:
        scoped_stats = (
            season_stats.filter(pl.col("season") == season_value)
            if "season" in season_stats.columns
            else season_stats
        )
        scoped_player_shot_profile = (
            player_shot_profile.filter(pl.col("season") == season_value)
            if not player_shot_profile.is_empty() and "season" in player_shot_profile.columns
            else player_shot_profile
        )
        if scoped_stats.is_empty():
            continue

        logger.info("Computing embeddings for %s (%d players)", season_value, len(scoped_stats))
        result = compute_embeddings(
            scoped_stats,
            scoped_player_shot_profile,
            artifact_dir=os.path.join(ARTIFACT_DIR, season_value),
        )
        if not result["embeddings"]:
            continue

        for emb in result["embeddings"]:
            emb["season"] = season_value
        for sim in result["similarity"]:
            sim["season"] = season_value

        embeddings_rows.extend(result["embeddings"])
        similarity_rows.extend(result["similarity"])
        upsert_rows(
            "gold",
            "model_artifacts",
            [{
                "model_name": "player_season_embeddings",
                "season": season_value,
                "trained_at": datetime.now(timezone.utc).isoformat(),
                "metadata_json": json.dumps(result["metadata"]),
            }],
            conflict_cols=["model_name", "season"],
        )
        summary.append(
            {
                "season": season_value,
                "n_embeddings": len(result["embeddings"]),
                "n_similarity_pairs": len(result["similarity"]),
                "n_clusters": result["metadata"]["n_clusters"],
                "silhouette_score": result["metadata"]["silhouette_score"],
            }
        )

    if not embeddings_rows:
        logger.warning("No embeddings computed for %s", target_seasons)
        return {"status": "skipped", "seasons": target_seasons}

    delete_where("gold", "player_season_embeddings", "season = ANY(%s)", [target_seasons])
    emb_count = insert_rows("gold", "player_season_embeddings", embeddings_rows)
    delete_where("gold", "player_season_similarity", "season = ANY(%s)", [target_seasons])
    sim_count = insert_rows("gold", "player_season_similarity", similarity_rows) if similarity_rows else 0
    latest = summary[-1]

    return {
        "status": "success",
        "rows_written": emb_count,
        "seasons": target_seasons,
        "n_embeddings": latest["n_embeddings"],
        "n_similarity_pairs": sim_count,
        "n_clusters": latest["n_clusters"],
        "silhouette_score": latest["silhouette_score"],
    }

# Pipeline graph declaration. Kept with task code so contributors can find ownership.
TASK_DEF = {'layer': 'gold',
 'task_type': 'gold',
 'inputs': ('gold.player_season_stats', 'gold.player_season_shot_profile'),
 'optional_inputs': (),
 'outputs': ('gold.player_season_embeddings', 'gold.player_season_similarity'),
 'mutates': (),
 'graphs': ('default',),
 'modes': ('live', 'fixture'),
 'required': True,
 'quality_outputs': ('gold.player_season_embeddings', 'gold.player_season_similarity'),
 'regular_season_only': True,
 'live_order': 600,
 'fixture_order': 480}
