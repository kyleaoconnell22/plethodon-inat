"""
Study 3: Plethodon Species Co-occurrence Patterns

Implements checkerboard analysis (C-score, SIM9 null model) and pairwise
co-occurrence tests for Plethodon species gridded into H3 hexagonal cells.
"""

import logging
from itertools import combinations
from pathlib import Path

import h3
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats
from tqdm import tqdm

from src.config import (
    CLEANED_DIR,
    FIGURES_DIR,
    NULL_MODEL_ITERATIONS,
    MIN_OBS_PER_CELL,
    H3_RES_BROAD,
    H3_RES_FINE,
    FOCUS_PAIRS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Load incidence matrix
# ---------------------------------------------------------------------------

def load_incidence(h3_res: int = 5) -> pd.DataFrame:
    """Load species × cell presence/absence matrix from parquet.

    Filters to cells with >= MIN_OBS_PER_CELL total observations.

    Returns
    -------
    pd.DataFrame
        Binary incidence matrix with species as rows and H3 cells as columns.
    """
    path = CLEANED_DIR / f"incidence_res{h3_res}.parquet"
    logger.info("Loading incidence matrix from %s", path)
    df = pd.read_parquet(path)

    # Expect rows = species, columns = H3 cell IDs (or vice-versa).
    # Convention: species as index, cells as columns.
    # If the parquet has cells as rows, transpose.
    if df.index.name == "species" or df.index[0] in [
        p[0] for p in FOCUS_PAIRS
    ]:
        pass  # already species × cells
    else:
        df = df.T

    # Filter to cells meeting minimum observation threshold
    col_totals = df.sum(axis=0)
    keep_cells = col_totals[col_totals >= MIN_OBS_PER_CELL].index
    df = df[keep_cells]
    logger.info(
        "Retained %d / %d cells with >= %d observations",
        len(keep_cells),
        len(col_totals),
        MIN_OBS_PER_CELL,
    )
    # Ensure binary
    df = (df > 0).astype(int)
    return df


# ---------------------------------------------------------------------------
# 2. Observed co-occurrence
# ---------------------------------------------------------------------------

def observed_cooccurrence(incidence: pd.DataFrame) -> pd.DataFrame:
    """Number of shared cells for each species pair.

    Returns symmetric species × species DataFrame.
    """
    mat = incidence.values  # species × cells
    obs = mat @ mat.T
    return pd.DataFrame(obs, index=incidence.index, columns=incidence.index)


# ---------------------------------------------------------------------------
# 3. Expected co-occurrence (independence)
# ---------------------------------------------------------------------------

def expected_cooccurrence(incidence: pd.DataFrame) -> pd.DataFrame:
    """Expected shared cells under independence: p_A × p_B × n_cells."""
    n_cells = incidence.shape[1]
    row_sums = incidence.sum(axis=1).values.astype(float)
    p = row_sums / n_cells
    expected = np.outer(p, p) * n_cells
    return pd.DataFrame(
        expected, index=incidence.index, columns=incidence.index
    )


# ---------------------------------------------------------------------------
# 4. C-score (Stone & Roberts 1990)
# ---------------------------------------------------------------------------

def c_score(incidence: pd.DataFrame) -> float:
    """Checkerboard statistic: mean over all species pairs of
    (r_i - S_ij)(r_j - S_ij).
    """
    mat = incidence.values
    n_sp = mat.shape[0]
    row_sums = mat.sum(axis=1)
    shared = mat @ mat.T  # S_ij

    total = 0.0
    n_pairs = 0
    for i in range(n_sp):
        for j in range(i + 1, n_sp):
            total += (row_sums[i] - shared[i, j]) * (
                row_sums[j] - shared[i, j]
            )
            n_pairs += 1
    return total / n_pairs if n_pairs > 0 else 0.0


# ---------------------------------------------------------------------------
# 5. SIM9 null model (fixed row & column sums, swap randomisation)
# ---------------------------------------------------------------------------

def sim9_null_model(
    incidence: pd.DataFrame, n_iter: int = 999
) -> np.ndarray:
    """SIM9 swap algorithm preserving row and column totals.

    For each iteration, performs 30 000 independent swaps on the binary
    matrix and records the C-score of the resulting matrix.

    Returns
    -------
    np.ndarray
        Array of length n_iter with null C-scores.
    """
    mat = incidence.values.copy().astype(np.int8)
    n_sp, n_sites = mat.shape
    n_swaps = 30_000

    row_sums = mat.sum(axis=1)

    null_scores = np.empty(n_iter, dtype=np.float64)
    rng = np.random.default_rng(seed=42)

    logger.info(
        "Running SIM9 null model: %d iterations × %d swaps", n_iter, n_swaps
    )

    for it in tqdm(range(n_iter), desc="SIM9"):
        # Perform swaps
        for _ in range(n_swaps):
            # Pick two random rows and two random columns
            r = rng.integers(0, n_sp, size=2)
            c = rng.integers(0, n_sites, size=2)
            if r[0] == r[1] or c[0] == c[1]:
                continue
            # Check for checkerboard pattern and swap
            a, b = r[0], r[1]
            x, y = c[0], c[1]
            if mat[a, x] == 1 and mat[b, y] == 1 and mat[a, y] == 0 and mat[b, x] == 0:
                mat[a, x] = 0
                mat[b, y] = 0
                mat[a, y] = 1
                mat[b, x] = 1
            elif mat[a, x] == 0 and mat[b, y] == 0 and mat[a, y] == 1 and mat[b, x] == 1:
                mat[a, x] = 1
                mat[b, y] = 1
                mat[a, y] = 0
                mat[b, x] = 0

        # Compute C-score for this randomised matrix
        shared = mat @ mat.T
        rs = mat.sum(axis=1)
        total = 0.0
        n_pairs = 0
        for i in range(n_sp):
            for j in range(i + 1, n_sp):
                total += (rs[i] - shared[i, j]) * (rs[j] - shared[i, j])
                n_pairs += 1
        null_scores[it] = total / n_pairs if n_pairs > 0 else 0.0

    return null_scores


# ---------------------------------------------------------------------------
# 6. Pairwise co-occurrence test
# ---------------------------------------------------------------------------

def pairwise_cooccurrence_test(
    incidence: pd.DataFrame, n_iter: int = 999
) -> pd.DataFrame:
    """Test each species pair for non-random co-occurrence via SIM9 null.

    For every pair with >0 observed shared cells, computes a standardised
    effect size (SES) and empirical p-value.

    Returns DataFrame with columns:
        species_a, species_b, obs_shared, exp_shared, ses, p_value, direction
    """
    mat = incidence.values.astype(np.int8)
    n_sp, n_sites = mat.shape
    species = list(incidence.index)
    n_swaps = 30_000
    rng = np.random.default_rng(seed=42)

    obs_shared_mat = mat @ mat.T

    # Collect null shared counts per iteration
    logger.info("Running pairwise null model: %d iterations", n_iter)
    null_shared = np.zeros((n_iter, n_sp, n_sp), dtype=np.int32)

    sim_mat = mat.copy()
    for it in tqdm(range(n_iter), desc="Pairwise null"):
        for _ in range(n_swaps):
            r = rng.integers(0, n_sp, size=2)
            c = rng.integers(0, n_sites, size=2)
            if r[0] == r[1] or c[0] == c[1]:
                continue
            a, b = r[0], r[1]
            x, y = c[0], c[1]
            if sim_mat[a, x] == 1 and sim_mat[b, y] == 1 and sim_mat[a, y] == 0 and sim_mat[b, x] == 0:
                sim_mat[a, x] = 0
                sim_mat[b, y] = 0
                sim_mat[a, y] = 1
                sim_mat[b, x] = 1
            elif sim_mat[a, x] == 0 and sim_mat[b, y] == 0 and sim_mat[a, y] == 1 and sim_mat[b, x] == 1:
                sim_mat[a, x] = 1
                sim_mat[b, y] = 1
                sim_mat[a, y] = 0
                sim_mat[b, x] = 0

        null_shared[it] = sim_mat @ sim_mat.T

    # Compile results for pairs with >0 observed shared cells
    rows = []
    for i in range(n_sp):
        for j in range(i + 1, n_sp):
            obs_s = int(obs_shared_mat[i, j])
            if obs_s == 0:
                continue
            null_vals = null_shared[:, i, j].astype(float)
            mean_null = null_vals.mean()
            std_null = null_vals.std(ddof=1)
            ses = (obs_s - mean_null) / std_null if std_null > 0 else 0.0

            # Two-tailed empirical p-value
            n_extreme = np.sum(np.abs(null_vals - mean_null) >= np.abs(obs_s - mean_null))
            p_val = (n_extreme + 1) / (n_iter + 1)

            direction = "positive" if obs_s > mean_null else "negative"
            rows.append(
                {
                    "species_a": species[i],
                    "species_b": species[j],
                    "obs_shared": obs_s,
                    "exp_shared": round(mean_null, 2),
                    "ses": round(ses, 3),
                    "p_value": round(p_val, 4),
                    "direction": direction,
                }
            )

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 7. Analyse focus pairs
# ---------------------------------------------------------------------------

def analyze_focus_pairs(
    incidence: pd.DataFrame, pairwise_results: pd.DataFrame
) -> pd.DataFrame:
    """Extract pairwise results for the predefined FOCUS_PAIRS."""
    rows = []
    for sp_a, sp_b in FOCUS_PAIRS:
        match = pairwise_results[
            ((pairwise_results["species_a"] == sp_a) & (pairwise_results["species_b"] == sp_b))
            | ((pairwise_results["species_a"] == sp_b) & (pairwise_results["species_b"] == sp_a))
        ]
        if match.empty:
            logger.warning("Focus pair not found in results: %s × %s", sp_a, sp_b)
            rows.append(
                {
                    "species_a": sp_a,
                    "species_b": sp_b,
                    "obs_shared": 0,
                    "exp_shared": np.nan,
                    "ses": np.nan,
                    "p_value": np.nan,
                    "direction": "no_overlap",
                }
            )
        else:
            rows.append(match.iloc[0].to_dict())
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 8. Heatmap of observed co-occurrence with significance
# ---------------------------------------------------------------------------

def plot_cooccurrence_matrix(
    obs_cooccur: pd.DataFrame,
    pairwise_results: pd.DataFrame,
    output_dir: Path | None = None,
) -> None:
    """Publication-ready heatmap with significance stars."""
    if output_dir is None:
        output_dir = FIGURES_DIR / "study3"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build annotation matrix with significance indicators
    annot = obs_cooccur.copy().astype(str)
    for _, row in pairwise_results.iterrows():
        a, b = row["species_a"], row["species_b"]
        p = row["p_value"]
        stars = ""
        if p < 0.001:
            stars = "***"
        elif p < 0.01:
            stars = "**"
        elif p < 0.05:
            stars = "*"
        if stars and a in annot.index and b in annot.columns:
            val = obs_cooccur.loc[a, b]
            annot.loc[a, b] = f"{val}{stars}"
            annot.loc[b, a] = f"{val}{stars}"

    # Shorten species names for axis labels
    short = {s: s.replace("Plethodon ", "P. ") for s in obs_cooccur.index}
    plot_df = obs_cooccur.rename(index=short, columns=short)
    annot_df = annot.rename(index=short, columns=short)

    fig, ax = plt.subplots(figsize=(10, 8))
    sns.heatmap(
        plot_df,
        annot=annot_df,
        fmt="",
        cmap="YlOrRd",
        linewidths=0.5,
        ax=ax,
        square=True,
        cbar_kws={"label": "Shared cells"},
    )
    ax.set_title("Observed Species Co-occurrence (shared H3 cells)")
    ax.set_xlabel("")
    ax.set_ylabel("")
    plt.xticks(rotation=45, ha="right")
    plt.yticks(rotation=0)
    plt.tight_layout()

    outpath = output_dir / "cooccurrence_heatmap.png"
    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved heatmap → %s", outpath)


# ---------------------------------------------------------------------------
# 9. Pair map (cell centroids coloured by occupancy)
# ---------------------------------------------------------------------------

def plot_pair_map(
    df_gridded: pd.DataFrame,
    species_a: str,
    species_b: str,
    h3_col: str = "h3_cell",
    output_dir: Path | None = None,
) -> None:
    """Map of cells occupied by each species, coloured by overlap."""
    if output_dir is None:
        output_dir = FIGURES_DIR / "study3"
    output_dir.mkdir(parents=True, exist_ok=True)

    cells_a = set(
        df_gridded.loc[df_gridded["species"] == species_a, h3_col]
    )
    cells_b = set(
        df_gridded.loc[df_gridded["species"] == species_b, h3_col]
    )
    overlap = cells_a & cells_b
    only_a = cells_a - overlap
    only_b = cells_b - overlap

    def centroids(cell_set):
        lats, lons = [], []
        for cell in cell_set:
            lat, lon = h3.cell_to_latlng(cell)
            lats.append(lat)
            lons.append(lon)
        return lons, lats

    fig, ax = plt.subplots(figsize=(10, 8))

    short_a = species_a.replace("Plethodon ", "P. ")
    short_b = species_b.replace("Plethodon ", "P. ")

    if only_a:
        x, y = centroids(only_a)
        ax.scatter(x, y, c="steelblue", s=20, alpha=0.7, label=f"{short_a} only")
    if only_b:
        x, y = centroids(only_b)
        ax.scatter(x, y, c="coral", s=20, alpha=0.7, label=f"{short_b} only")
    if overlap:
        x, y = centroids(overlap)
        ax.scatter(x, y, c="purple", s=30, alpha=0.9, label="Both", zorder=5)

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"Co-occurrence: {short_a} × {short_b}")
    ax.legend(loc="best")
    plt.tight_layout()

    safe_a = species_a.replace(" ", "_")
    safe_b = species_b.replace(" ", "_")
    outpath = output_dir / f"pair_map_{safe_a}_{safe_b}.png"
    fig.savefig(outpath, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved pair map → %s", outpath)


# ---------------------------------------------------------------------------
# 10. Main entry point
# ---------------------------------------------------------------------------

def run(h3_res: int = 5) -> None:
    """Run the full Study 3 co-occurrence analysis."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)s  %(levelname)s  %(message)s",
    )
    output_dir = FIGURES_DIR / "study3"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=== Study 3: Co-occurrence analysis (H3 res %d) ===", h3_res)

    # Load incidence matrix
    incidence = load_incidence(h3_res=h3_res)
    logger.info(
        "Incidence matrix: %d species × %d cells", *incidence.shape
    )

    # Observed and expected co-occurrence
    obs_cooccur = observed_cooccurrence(incidence)
    exp_cooccur = expected_cooccurrence(incidence)
    logger.info("Observed & expected co-occurrence computed")

    # C-score and SIM9 null model
    obs_c = c_score(incidence)
    logger.info("Observed C-score: %.2f", obs_c)

    null_c = sim9_null_model(incidence, n_iter=NULL_MODEL_ITERATIONS)
    mean_null = null_c.mean()
    std_null = null_c.std(ddof=1)
    ses_c = (obs_c - mean_null) / std_null if std_null > 0 else 0.0
    p_c = (np.sum(null_c >= obs_c) + 1) / (NULL_MODEL_ITERATIONS + 1)
    logger.info(
        "C-score SES=%.3f  p=%.4f  (null mean=%.2f, sd=%.2f)",
        ses_c, p_c, mean_null, std_null,
    )

    # Save C-score summary
    cscore_summary = pd.DataFrame(
        [
            {
                "observed_c_score": round(obs_c, 4),
                "null_mean": round(mean_null, 4),
                "null_sd": round(std_null, 4),
                "ses": round(ses_c, 4),
                "p_value": round(p_c, 4),
                "n_iterations": NULL_MODEL_ITERATIONS,
            }
        ]
    )
    cscore_path = CLEANED_DIR / f"cscore_summary_res{h3_res}.csv"
    cscore_summary.to_csv(cscore_path, index=False)
    logger.info("Saved C-score summary → %s", cscore_path)

    # Pairwise tests
    pairwise_results = pairwise_cooccurrence_test(
        incidence, n_iter=NULL_MODEL_ITERATIONS
    )
    pairwise_path = CLEANED_DIR / f"pairwise_cooccurrence_res{h3_res}.csv"
    pairwise_results.to_csv(pairwise_path, index=False)
    logger.info(
        "Saved %d pairwise results → %s", len(pairwise_results), pairwise_path
    )

    n_sig = (pairwise_results["p_value"] < 0.05).sum()
    n_pos = (
        (pairwise_results["p_value"] < 0.05)
        & (pairwise_results["direction"] == "positive")
    ).sum()
    n_neg = (
        (pairwise_results["p_value"] < 0.05)
        & (pairwise_results["direction"] == "negative")
    ).sum()
    logger.info(
        "Significant pairs: %d (%d positive, %d negative)", n_sig, n_pos, n_neg
    )

    # Focus pairs
    focus = analyze_focus_pairs(incidence, pairwise_results)
    focus_path = CLEANED_DIR / f"focus_pairs_res{h3_res}.csv"
    focus.to_csv(focus_path, index=False)
    logger.info("Focus pair results:\n%s", focus.to_string(index=False))

    # Figures
    plot_cooccurrence_matrix(obs_cooccur, pairwise_results, output_dir)

    # Pair maps for focus species
    gridded_path = CLEANED_DIR / "plethodon_gridded.parquet"
    if gridded_path.exists():
        df_gridded = pd.read_parquet(gridded_path)
        h3_col = f"h3_res{h3_res}"
        for sp_a, sp_b in FOCUS_PAIRS:
            plot_pair_map(df_gridded, sp_a, sp_b, h3_col, output_dir)
    else:
        logger.warning(
            "Gridded data not found at %s — skipping pair maps", gridded_path
        )

    logger.info("=== Study 3 complete ===")


if __name__ == "__main__":
    run()
