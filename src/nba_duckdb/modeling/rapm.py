"""RAPM (Regularized Adjusted Plus-Minus).

Ridge regression on lineup stint data to isolate individual player impact.
Design matrix: +1 for offense players, -1 for defense players.
Target: net points per 100 possessions.

Cross-validated with GroupKFold by game to avoid leakage.
Bootstrap confidence intervals by resampling games.
Bayesian-style blending with a BPM approximation prior for low-minute players.
"""

import logging

import numpy as np
import polars as pl
from scipy import sparse
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold

logger = logging.getLogger("nba_duckdb.modeling.rapm")

# Default regularization search grid
DEFAULT_LAMBDAS = [0.01, 0.1, 1.0, 10.0, 100.0, 1000.0, 10000.0]

# Minutes threshold for full trust in RAPM (below this, blend with BPM prior)
MIN_TRUST_MINUTES = 500.0


def build_design_matrix(
    lineups_df: pl.DataFrame,
    games_df: pl.DataFrame,
    pace_lookup: dict[int, float],
) -> tuple[sparse.csr_matrix, np.ndarray, np.ndarray, list[int], np.ndarray]:
    """Build the RAPM design matrix from lineup stint data.

    For each stint, creates a row with +1 for players on the offensive team
    and -1 for players on the defensive team. Stints are paired by matching
    clock intervals when available, falling back to (game_id, stint_number,
    period) for synthetic or legacy datasets.

    Returns:
        X: sparse design matrix (n_stints, n_players)
        y: net rating per 100 possessions
        weights: sqrt(possessions) per stint
        player_ids: ordered list of player IDs (column index → player_id)
        game_ids: game_id per row (for GroupKFold)
    """
    # Build home team lookup from games
    home_teams: dict[str, int] = {}
    for row in games_df.iter_rows(named=True):
        gid = row.get("game_id")
        htid = row.get("home_team_id")
        if gid and htid:
            home_teams[gid] = htid

    # Collect all unique player IDs
    all_player_ids: set[int] = set()
    for pid_str in lineups_df["player_ids_str"].to_list():
        if pid_str:
            for pid in str(pid_str).split(","):
                try:
                    all_player_ids.add(int(pid.strip()))
                except ValueError:
                    pass

    player_ids = sorted(all_player_ids)
    pid_to_idx = {pid: idx for idx, pid in enumerate(player_ids)}
    n_players = len(player_ids)

    logger.info("Building design matrix: %d unique players", n_players)

    # Group stints into pairs. Real parsed lineups can have team-local
    # stint_number values, so clock intervals are the most reliable shared key.
    stint_groups: dict[tuple, list[dict]] = {}
    for row in lineups_df.iter_rows(named=True):
        start_clock = row.get("start_clock_seconds")
        end_clock = row.get("end_clock_seconds")
        if start_clock is not None and end_clock is not None:
            key = (row["game_id"], row.get("period"), float(start_clock), float(end_clock))
        else:
            key = (row["game_id"], row.get("stint_number"), row.get("period"))
        stint_groups.setdefault(key, []).append(row)

    # Default pace for possession estimation
    default_pace = 100.0  # possessions per 48 min

    rows_data = []  # (row_indices, col_indices, values) for sparse matrix
    y_list = []
    w_list = []
    gid_list = []
    row_idx = 0

    for key, stints in stint_groups.items():
        if len(stints) != 2:
            continue  # Need exactly 2 teams per stint pair

        game_id = key[0]

        for stint in stints:
            team_id = stint.get("team_id")
            pts_for = stint.get("points_for") or 0
            pts_against = stint.get("points_against") or 0
            duration = stint.get("duration_seconds") or 0

            if duration < 5:  # Skip very short stints (< 5 seconds)
                continue

            # Parse player IDs for this team
            pid_str = stint.get("player_ids_str", "")
            try:
                team_pids = [int(p.strip()) for p in str(pid_str).split(",") if p.strip()]
            except ValueError:
                continue

            if len(team_pids) != 5:
                continue

            # Find opponent team's players
            opp_stint = [s for s in stints if s.get("team_id") != team_id]
            if not opp_stint:
                continue
            opp_pid_str = opp_stint[0].get("player_ids_str", "")
            try:
                opp_pids = [int(p.strip()) for p in str(opp_pid_str).split(",") if p.strip()]
            except ValueError:
                continue

            if len(opp_pids) != 5:
                continue

            # Estimate possessions
            pace = pace_lookup.get(team_id, default_pace)
            est_poss = duration / (48 * 60) * pace
            if est_poss < 0.1:
                continue

            # Net rating per 100 possessions
            net_pts = pts_for - pts_against
            net_per_100 = (net_pts / est_poss) * 100.0

            # Build sparse row: +1 for this team's players, -1 for opponent
            col_indices = []
            values = []
            for pid in team_pids:
                idx = pid_to_idx.get(pid)
                if idx is not None:
                    col_indices.append(idx)
                    values.append(1.0)
            for pid in opp_pids:
                idx = pid_to_idx.get(pid)
                if idx is not None:
                    col_indices.append(idx)
                    values.append(-1.0)

            rows_data.append((row_idx, col_indices, values))
            y_list.append(net_per_100)
            w_list.append(np.sqrt(est_poss))
            gid_list.append(game_id)
            row_idx += 1

    if not rows_data:
        raise ValueError("No valid stint pairs found")

    # Build sparse matrix
    n_rows = len(rows_data)
    all_row_indices = []
    all_col_indices = []
    all_values = []
    for r_idx, cols, vals in rows_data:
        for c, v in zip(cols, vals):
            all_row_indices.append(r_idx)
            all_col_indices.append(c)
            all_values.append(v)

    X = sparse.csr_matrix(
        (all_values, (all_row_indices, all_col_indices)),
        shape=(n_rows, n_players),
    )

    y = np.array(y_list, dtype=np.float64)
    weights = np.array(w_list, dtype=np.float64)
    game_ids_arr = np.array(gid_list)

    logger.info("Design matrix: %d stints × %d players, density=%.4f",
                n_rows, n_players, X.nnz / (n_rows * n_players))

    return X, y, weights, player_ids, game_ids_arr


def fit_rapm(
    X: sparse.csr_matrix,
    y: np.ndarray,
    weights: np.ndarray,
    game_ids: np.ndarray,
    lambdas: list[float] | None = None,
    n_folds: int = 5,
) -> tuple[np.ndarray, float, float]:
    """Fit ridge regression with GroupKFold cross-validation.

    Returns (coefficients, best_lambda, cv_mse).
    """
    if lambdas is None:
        lambdas = DEFAULT_LAMBDAS

    # Apply weights: multiply X rows and y by sqrt(weight)
    W = np.sqrt(weights)
    X_w = X.multiply(W[:, np.newaxis]).tocsr()
    y_w = y * W

    # Cross-validate
    gkf = GroupKFold(n_splits=min(n_folds, len(np.unique(game_ids))))
    best_lambda = lambdas[0]
    best_mse = float("inf")

    for lam in lambdas:
        fold_mses = []
        for train_idx, test_idx in gkf.split(X_w, y_w, groups=game_ids):
            model = Ridge(alpha=lam, fit_intercept=False)
            model.fit(X_w[train_idx], y_w[train_idx])
            preds = model.predict(X_w[test_idx])
            mse = np.mean((preds - y_w[test_idx]) ** 2)
            fold_mses.append(mse)

        avg_mse = np.mean(fold_mses)
        if avg_mse < best_mse:
            best_mse = avg_mse
            best_lambda = lam

    logger.info("Best lambda=%.2f, CV MSE=%.4f", best_lambda, best_mse)

    # Refit on all data with best lambda
    final_model = Ridge(alpha=best_lambda, fit_intercept=False)
    final_model.fit(X_w, y_w)

    return final_model.coef_, best_lambda, best_mse


def bootstrap_ci(
    X: sparse.csr_matrix,
    y: np.ndarray,
    weights: np.ndarray,
    game_ids: np.ndarray,
    lam: float,
    n_boot: int = 100,
    ci: float = 0.90,
) -> tuple[np.ndarray, np.ndarray]:
    """Bootstrap confidence intervals by resampling games.

    Returns (lower_bounds, upper_bounds) arrays of shape (n_players,).
    """
    unique_games = np.unique(game_ids)
    n_games = len(unique_games)
    n_players = X.shape[1]

    W = np.sqrt(weights)
    boot_coefs = np.zeros((n_boot, n_players))

    alpha_lo = (1 - ci) / 2
    alpha_hi = 1 - alpha_lo

    for b in range(n_boot):
        # Resample games with replacement
        sampled_games = np.random.choice(unique_games, size=n_games, replace=True)

        # Find indices for sampled games
        indices = []
        for g in sampled_games:
            idx = np.where(game_ids == g)[0]
            indices.extend(idx.tolist())
        indices = np.array(indices)

        X_b = X[indices]
        y_b = y[indices]
        w_b = W[indices]

        X_bw = X_b.multiply(w_b[:, np.newaxis]).tocsr()
        y_bw = y_b * w_b

        model = Ridge(alpha=lam, fit_intercept=False)
        model.fit(X_bw, y_bw)
        boot_coefs[b] = model.coef_

    lower = np.percentile(boot_coefs, alpha_lo * 100, axis=0)
    upper = np.percentile(boot_coefs, alpha_hi * 100, axis=0)

    return lower, upper


def blend_with_prior(
    rapm_values: np.ndarray,
    minutes: np.ndarray,
    prior_values: np.ndarray,
    min_trust_minutes: float = MIN_TRUST_MINUTES,
) -> np.ndarray:
    """Bayesian blending: fade RAPM toward BPM prior for low-minute players.

    alpha = min(1.0, minutes / min_trust_minutes)
    blended = alpha * rapm + (1 - alpha) * prior
    """
    alpha = np.clip(minutes / min_trust_minutes, 0.0, 1.0)
    return alpha * rapm_values + (1 - alpha) * prior_values
