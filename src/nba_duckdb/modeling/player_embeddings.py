"""Player embeddings.

PCA dimensionality reduction + UMAP 2D projection + GMM clustering
on per-player statistical profiles. Produces embeddings for visualization
and cosine similarity for player comparison.
"""

import json
import logging
import os

import joblib
import numpy as np
import polars as pl
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler

from nba_duckdb.modeling.artifact_paths import artifact_dir

logger = logging.getLogger("nba_duckdb.modeling.player_embeddings")

ARTIFACT_DIR = artifact_dir("embeddings")

# Feature definitions
STAT_FEATURES = [
    "pts_per_36", "avg_ts_pct", "avg_usg_pct", "fg_pct", "fg3_pct",
    "ast_per_36", "reb_per_36",
    "spg", "bpg", "topg",
    "avg_off_rating", "avg_def_rating", "avg_game_score",
]

MIN_MPG = 15.0
MIN_GP = 20


def _compute_per36(stats_df: pl.DataFrame) -> pl.DataFrame:
    """Ensure per-36 columns exist, computing from per-game if needed."""
    df = stats_df

    if "ast_per_36" not in df.columns and "apg" in df.columns and "mpg" in df.columns:
        df = df.with_columns(
            ((pl.col("apg") / pl.col("mpg").clip(1)) * 36).alias("ast_per_36"),
        )
    if "reb_per_36" not in df.columns and "rpg" in df.columns and "mpg" in df.columns:
        df = df.with_columns(
            ((pl.col("rpg") / pl.col("mpg").clip(1)) * 36).alias("reb_per_36"),
        )
    if "pts_per_36" not in df.columns and "ppg" in df.columns and "mpg" in df.columns:
        df = df.with_columns(
            ((pl.col("ppg") / pl.col("mpg").clip(1)) * 36).alias("pts_per_36"),
        )

    return df


def _join_shot_diet(
    stats_df: pl.DataFrame,
    player_shot_profile_df: pl.DataFrame,
) -> pl.DataFrame:
    """Add shot diet features (paint, midrange, three freq) from player shot profile rows."""
    if player_shot_profile_df.is_empty():
        return stats_df.with_columns(
            pl.lit(0.0).alias("diet_paint"),
            pl.lit(0.0).alias("diet_mid"),
            pl.lit(0.0).alias("diet_three"),
        )

    # Pivot player shot profile rows: player_id → freq_pct by bucket
    player_diets = {}
    for row in player_shot_profile_df.iter_rows(named=True):
        pid = row.get("player_id")
        bucket = str(row.get("shot_bucket", "")).lower()
        freq = float(row.get("freq_pct", 0) or 0)
        if pid not in player_diets:
            player_diets[pid] = {"diet_paint": 0.0, "diet_mid": 0.0, "diet_three": 0.0}
        if "paint" in bucket or "0-3" in bucket or "restricted" in bucket:
            player_diets[pid]["diet_paint"] += freq
        elif "3pt" in bucket or "three" in bucket or "3p" in bucket:
            player_diets[pid]["diet_three"] += freq
        else:
            player_diets[pid]["diet_mid"] += freq

    diet_rows = [{"player_id": pid, **diets} for pid, diets in player_diets.items()]
    if not diet_rows:
        return stats_df.with_columns(
            pl.lit(0.0).alias("diet_paint"),
            pl.lit(0.0).alias("diet_mid"),
            pl.lit(0.0).alias("diet_three"),
        )

    diet_df = pl.DataFrame(diet_rows)
    return stats_df.join(diet_df, on="player_id", how="left").with_columns(
        pl.col("diet_paint").fill_null(0.0),
        pl.col("diet_mid").fill_null(0.0),
        pl.col("diet_three").fill_null(0.0),
    )


def compute_embeddings(
    season_stats: pl.DataFrame,
    player_shot_profile: pl.DataFrame,
    n_pca_variance: float = 0.90,
    umap_neighbors: int = 15,
    umap_min_dist: float = 0.1,
    gmm_k_range: tuple[int, int] = (4, 12),
    artifact_dir: str | None = None,
) -> dict:
    """Full embedding pipeline: filter → standardize → PCA → UMAP → GMM.

    Returns dict with 'embeddings', 'similarity', 'metadata'.
    """
    # 1. Filter eligible players
    stats = _compute_per36(season_stats)
    eligible = stats.filter(
        (pl.col("mpg") >= MIN_MPG) & (pl.col("games_played") >= MIN_GP)
    )

    if len(eligible) < 20:
        logger.warning("Only %d eligible players (need >= 20)", len(eligible))
        return {"embeddings": [], "similarity": [], "metadata": {"error": "too few players"}}

    # 2. Join shot diet
    eligible = _join_shot_diet(eligible, player_shot_profile)

    # 3. Prepare feature matrix
    all_features = STAT_FEATURES + ["diet_paint", "diet_mid", "diet_three"]
    available_features = [f for f in all_features if f in eligible.columns]

    # Fill nulls with 0
    for col in available_features:
        eligible = eligible.with_columns(pl.col(col).fill_null(0.0).cast(pl.Float64))

    X = eligible.select(available_features).to_numpy()
    player_ids = eligible["player_id"].to_list()
    player_names = eligible["player_name"].to_list()
    team_ids = eligible["team_id"].to_list()
    positions = eligible["position"].to_list() if "position" in eligible.columns else [""] * len(player_ids)

    logger.info("Embedding %d players with %d features", len(player_ids), len(available_features))

    # 4. Standardize
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Replace any NaN/inf after scaling
    X_scaled = np.nan_to_num(X_scaled, nan=0.0, posinf=0.0, neginf=0.0)

    # 5. PCA
    pca = PCA(n_components=min(n_pca_variance, X_scaled.shape[1] - 1))
    X_pca = pca.fit_transform(X_scaled)
    n_components = X_pca.shape[1]

    logger.info(
        "PCA: %d components, explained variance: %s",
        n_components,
        [round(v, 3) for v in pca.explained_variance_ratio_.tolist()],
    )

    # 6. UMAP
    try:
        import umap
        # Initialize from PCA first 2 components for stability
        init = X_pca[:, :2] if X_pca.shape[1] >= 2 else "spectral"
        reducer = umap.UMAP(
            n_components=2,
            n_neighbors=min(umap_neighbors, len(player_ids) - 1),
            min_dist=umap_min_dist,
            metric="cosine",
            random_state=42,
            init=init if isinstance(init, str) else init,
        )
        X_umap = reducer.fit_transform(X_pca)
    except Exception as e:
        logger.warning("UMAP failed, falling back to PCA first 2 components: %s", e)
        X_umap = X_pca[:, :2] if X_pca.shape[1] >= 2 else np.zeros((len(player_ids), 2))
        reducer = None

    # 7. GMM clustering on PCA space
    best_k = gmm_k_range[0]
    best_bic = float("inf")
    bic_scores = {}

    for k in range(gmm_k_range[0], min(gmm_k_range[1] + 1, len(player_ids))):
        gmm = GaussianMixture(n_components=k, random_state=42, covariance_type="full")
        gmm.fit(X_pca)
        bic = gmm.bic(X_pca)
        bic_scores[k] = round(bic, 2)
        if bic < best_bic:
            best_bic = bic
            best_k = k

    final_gmm = GaussianMixture(n_components=best_k, random_state=42, covariance_type="full")
    final_gmm.fit(X_pca)
    cluster_labels = final_gmm.predict(X_pca)

    # Silhouette score
    sil = silhouette_score(X_pca, cluster_labels) if best_k > 1 else 0.0

    logger.info("GMM: K=%d (BIC=%.1f), silhouette=%.3f", best_k, best_bic, sil)

    # 8. Auto-label clusters by dominant features
    cluster_names = {}
    for k in range(best_k):
        mask = cluster_labels == k
        if mask.sum() == 0:
            cluster_names[k] = f"Cluster {k}"
            continue
        cluster_mean = X_scaled[mask].mean(axis=0)
        # Find top 2 features for this cluster
        top_idx = np.argsort(np.abs(cluster_mean))[-2:][::-1]
        top_features = [available_features[i] for i in top_idx]
        signs = ["+" if cluster_mean[i] > 0 else "-" for i in top_idx]

        # Map to readable labels
        label_map = {
            "pts_per_36": "Scoring", "avg_ts_pct": "Efficiency", "avg_usg_pct": "Usage",
            "fg_pct": "FG%", "fg3_pct": "Shooting", "ast_per_36": "Playmaking",
            "reb_per_36": "Rebounding", "spg": "Steals", "bpg": "Rim Protection",
            "topg": "Turnovers", "avg_off_rating": "Offense", "avg_def_rating": "Defense",
            "avg_game_score": "Impact", "diet_paint": "Paint", "diet_mid": "Midrange",
            "diet_three": "3PT Heavy",
        }
        readable = [f"{signs[i]}{label_map.get(top_features[i], top_features[i])}"
                     for i in range(len(top_features))]
        cluster_names[k] = " / ".join(readable)

    logger.info("Clusters: %s", {k: f"{v} ({(cluster_labels == k).sum()} players)"
                                   for k, v in cluster_names.items()})

    # 9. Cosine similarity in PCA space
    cos_sim = cosine_similarity(X_pca)

    # 10. Build output
    embeddings = []
    for i, pid in enumerate(player_ids):
        emb = {
            "player_id": pid,
            "player_name": player_names[i],
            "team_id": team_ids[i],
            "position": positions[i] or "",
            "umap_x": round(float(X_umap[i, 0]), 4),
            "umap_y": round(float(X_umap[i, 1]), 4),
            "cluster_id": int(cluster_labels[i]),
            "cluster_label": cluster_names.get(int(cluster_labels[i]), ""),
        }
        # Add PCA components (pad to 5)
        for j in range(5):
            emb[f"pca_{j+1}"] = round(float(X_pca[i, j]), 4) if j < n_components else 0.0
        embeddings.append(emb)

    # Build similarity (top 10 per player)
    similarity = []
    for i, pid in enumerate(player_ids):
        sims = cos_sim[i]
        # Exclude self
        sim_indices = np.argsort(sims)[::-1]
        rank = 0
        for j in sim_indices:
            if j == i:
                continue
            rank += 1
            if rank > 10:
                break
            similarity.append({
                "player_id": pid,
                "similar_player_id": player_ids[j],
                "similar_player_name": player_names[j],
                "similar_team_id": team_ids[j],
                "similar_position": positions[j] or "",
                "similar_ppg": 0.0,
                "similar_rpg": 0.0,
                "similar_apg": 0.0,
                "similarity_score": round(float(sims[j]) * 100, 1),
                "rank": rank,
            })

    # Fill in ppg/rpg/apg for similar players
    stat_lookup = {}
    for row in eligible.iter_rows(named=True):
        stat_lookup[row.get("player_id")] = row
    for sim_row in similarity:
        s = stat_lookup.get(sim_row["similar_player_id"], {})
        sim_row["similar_ppg"] = round(float(s.get("ppg", 0) or 0), 1)
        sim_row["similar_rpg"] = round(float(s.get("rpg", 0) or 0), 1)
        sim_row["similar_apg"] = round(float(s.get("apg", 0) or 0), 1)

    metadata = {
        "n_players": len(player_ids),
        "n_features": len(available_features),
        "feature_names": available_features,
        "n_pca_components": n_components,
        "explained_variance": [round(v, 4) for v in pca.explained_variance_ratio_.tolist()],
        "total_variance_explained": round(sum(pca.explained_variance_ratio_), 4),
        "n_clusters": best_k,
        "bic_scores": bic_scores,
        "silhouette_score": round(sil, 4),
        "cluster_labels": cluster_names,
    }

    # Save artifacts
    target_artifact_dir = artifact_dir or ARTIFACT_DIR
    os.makedirs(target_artifact_dir, exist_ok=True)
    joblib.dump(scaler, os.path.join(target_artifact_dir, "scaler.joblib"))
    joblib.dump(pca, os.path.join(target_artifact_dir, "pca.joblib"))
    joblib.dump(final_gmm, os.path.join(target_artifact_dir, "gmm.joblib"))
    if reducer is not None:
        joblib.dump(reducer, os.path.join(target_artifact_dir, "umap.joblib"))
    with open(os.path.join(target_artifact_dir, "metadata.json"), "w") as f:
        json.dump(metadata, f, indent=2)

    return {"embeddings": embeddings, "similarity": similarity, "metadata": metadata}
