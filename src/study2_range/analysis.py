"""
Study 2: Effort-Corrected Geographic Expansion in Plethodon Salamanders

Quantifies whether apparent range expansions in iNaturalist occurrence data
reflect true distributional shifts or are artifacts of spatially biased
sampling effort.  Uses rarefaction-based effort correction and cumulative
range-fill curves at the H3 hexagonal grid scale.
"""

import logging
from pathlib import Path

import h3
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.config import CLEANED_DIR, FIGURES_DIR, YEAR_MIN, YEAR_MAX, H3_RES_BROAD

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")


# ---------------------------------------------------------------------------
# 1. Data loading
# ---------------------------------------------------------------------------

def load_data():
    """Load gridded parquet and return observations + cell-level effort table."""
    parquet_path = CLEANED_DIR / "plethodon_gridded.parquet"
    logger.info("Loading gridded data from %s", parquet_path)
    df = pd.read_parquet(parquet_path)

    # Build cell-level effort table: total Plethodon obs per cell per year
    h3_col = f"h3_res{H3_RES_BROAD}"
    if h3_col not in df.columns:
        # Fall back to any h3 column present
        h3_cols = [c for c in df.columns if c.startswith("h3_")]
        if h3_cols:
            h3_col = h3_cols[0]
            logger.warning("Expected column h3_res%d not found; using %s", H3_RES_BROAD, h3_col)
        else:
            raise ValueError("No H3 cell column found in the gridded parquet.")

    cell_effort = (
        df.groupby([h3_col, "year"])
        .size()
        .reset_index(name="plethodon_obs")
    )

    logger.info(
        "Loaded %d observations across %d unique cells",
        len(df),
        df[h3_col].nunique(),
    )
    return df, cell_effort, h3_col


# ---------------------------------------------------------------------------
# 2. Effort calculation
# ---------------------------------------------------------------------------

def calculate_effort(df, h3_col, effort_df=None):
    """
    For each H3 cell x year, calculate a sampling-effort proxy.

    If *effort_df* (total iNat observations per cell/year, all taxa) is
    provided, use it.  Otherwise fall back to total Plethodon obs per cell.

    Returns DataFrame with columns: h3_cell, year, plethodon_obs, total_effort.
    """
    pleth_effort = (
        df.groupby([h3_col, "year"])
        .size()
        .reset_index(name="plethodon_obs")
        .rename(columns={h3_col: "h3_cell"})
    )

    if effort_df is not None:
        # effort_df expected to have columns: h3_cell, year, total_effort
        out = pleth_effort.merge(effort_df, on=["h3_cell", "year"], how="left")
        out["total_effort"] = out["total_effort"].fillna(out["plethodon_obs"])
    else:
        out = pleth_effort.copy()
        out["total_effort"] = out["plethodon_obs"]

    logger.info("Effort table: %d cell-year rows", len(out))
    return out


# ---------------------------------------------------------------------------
# 3. Rarefaction correction
# ---------------------------------------------------------------------------

def rarefaction_correct(df, h3_col, effort_col="total_effort", n_subsamples=100):
    """
    Rarefaction-based effort correction.

    For each cell x year, subsample observations down to the minimum effort
    level (across all cell-years with data), repeated *n_subsamples* times.
    Returns mean effort-corrected species richness per cell x year.
    """
    rng = np.random.default_rng(42)

    grouped = df.groupby([h3_col, "year"])

    # Determine the minimum cell-year sample size for rarefaction depth
    cell_year_sizes = grouped.size()
    min_n = int(cell_year_sizes.quantile(0.05))  # 5th percentile as floor
    min_n = max(min_n, 1)
    logger.info("Rarefaction depth (5th-percentile effort): %d observations", min_n)

    records = []
    for (cell, year), grp in grouped:
        n = len(grp)
        if n < min_n:
            # Too few observations — use raw count
            sp_count = grp["species"].nunique() if "species" in grp.columns else 0
            records.append({
                "h3_cell": cell,
                "year": year,
                "raw_species": sp_count,
                "corrected_species": sp_count,
                "n_obs": n,
            })
            continue

        species_col = "species" if "species" in grp.columns else "scientific_name"
        raw_species = grp[species_col].nunique()

        rarefied_counts = []
        idx = np.arange(n)
        for _ in range(n_subsamples):
            sub_idx = rng.choice(idx, size=min_n, replace=False)
            sub = grp.iloc[sub_idx]
            rarefied_counts.append(sub[species_col].nunique())

        records.append({
            "h3_cell": cell,
            "year": year,
            "raw_species": raw_species,
            "corrected_species": np.mean(rarefied_counts),
            "n_obs": n,
        })

    result = pd.DataFrame(records)
    logger.info("Rarefaction complete: %d cell-year records", len(result))
    return result


# ---------------------------------------------------------------------------
# 4. Range-fill curves
# ---------------------------------------------------------------------------

def range_fill_curves(df, h3_col, species_list=None):
    """
    Compute cumulative unique occupied cells over time for each species.

    Returns dict of {species: DataFrame(year, raw_cells_cumulative,
    corrected_cells_cumulative)}.

    The 'corrected' curve counts a cell as occupied only if its effort-
    corrected species count still includes that species (approximated by
    resampling presence at the rarefaction depth).
    """
    species_col = "species" if "species" in df.columns else "scientific_name"
    years = list(range(YEAR_MIN, YEAR_MAX + 1))

    if species_list is None:
        species_list = sorted(df[species_col].unique())

    # Pre-compute rarefaction depth
    cell_year_sizes = df.groupby([h3_col, "year"]).size()
    min_n = max(int(cell_year_sizes.quantile(0.05)), 1)
    rng = np.random.default_rng(99)
    n_sub = 50  # subsamples for presence correction

    curves = {}
    for sp in species_list:
        sp_df = df[df[species_col] == sp]
        if sp_df.empty:
            continue

        raw_cumul = []
        corrected_cumul = []
        raw_seen = set()
        corrected_seen = set()

        for yr in years:
            yr_df = sp_df[sp_df["year"] <= yr]
            raw_seen = set(yr_df[h3_col].unique())
            raw_cumul.append(len(raw_seen))

            # For corrected: check each newly appearing cell has the species
            # surviving rarefaction
            yr_exact = sp_df[sp_df["year"] == yr]
            for cell in yr_exact[h3_col].unique():
                if cell in corrected_seen:
                    continue
                # All obs in this cell-year
                cell_all = df[(df[h3_col] == cell) & (df["year"] == yr)]
                n_cell = len(cell_all)
                if n_cell <= min_n:
                    corrected_seen.add(cell)
                    continue
                # Probability species is detected in rarefied subsample
                detections = 0
                idx = np.arange(n_cell)
                for _ in range(n_sub):
                    sub_idx = rng.choice(idx, size=min_n, replace=False)
                    if sp in cell_all.iloc[sub_idx][species_col].values:
                        detections += 1
                if detections / n_sub >= 0.5:
                    corrected_seen.add(cell)

            corrected_cumul.append(len(corrected_seen))

        curves[sp] = pd.DataFrame({
            "year": years,
            "raw_cells_cumulative": raw_cumul,
            "corrected_cells_cumulative": corrected_cumul,
        })

    logger.info("Range-fill curves computed for %d species", len(curves))
    return curves


# ---------------------------------------------------------------------------
# 5. Detect novel cells
# ---------------------------------------------------------------------------

def detect_novel_cells(df, h3_col, recent_years=3):
    """
    Identify cells where a species was first detected in the most recent
    *recent_years*, provided the cell had sufficient prior sampling effort.

    Returns DataFrame with columns: species, h3_cell, first_detection_year,
    prior_effort_years, confidence.
    """
    species_col = "species" if "species" in df.columns else "scientific_name"
    cutoff = YEAR_MAX - recent_years + 1  # e.g. 2024 for recent_years=3

    records = []
    for sp, sp_df in df.groupby(species_col):
        cells_by_year = sp_df.groupby(h3_col)["year"].min().reset_index()
        cells_by_year.columns = [h3_col, "first_year"]

        novel = cells_by_year[cells_by_year["first_year"] >= cutoff]
        for _, row in novel.iterrows():
            cell = row[h3_col]
            first_yr = int(row["first_year"])

            # How many prior years had ANY Plethodon observation in this cell?
            prior = df[
                (df[h3_col] == cell)
                & (df["year"] < first_yr)
            ]["year"].nunique()

            # Confidence heuristic:
            #   high  = cell sampled >= 5 prior years without this species
            #   med   = cell sampled 2-4 prior years
            #   low   = cell sampled 0-1 prior years (may just be new effort)
            if prior >= 5:
                confidence = "high"
            elif prior >= 2:
                confidence = "medium"
            else:
                confidence = "low"

            records.append({
                "species": sp,
                "h3_cell": cell,
                "first_detection_year": first_yr,
                "prior_effort_years": prior,
                "confidence": confidence,
            })

    result = pd.DataFrame(records)
    logger.info(
        "Novel-cell detection: %d candidates (%d high confidence)",
        len(result),
        (result["confidence"] == "high").sum() if len(result) else 0,
    )
    return result


# ---------------------------------------------------------------------------
# 6. Plot: range-fill curve
# ---------------------------------------------------------------------------

def plot_range_fill(curves_dict, species, output_dir=None):
    """
    Publication-ready dual-line figure: raw vs effort-corrected cumulative
    cell counts for a single species.
    """
    if output_dir is None:
        output_dir = FIGURES_DIR / "study2"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if species not in curves_dict:
        logger.warning("No curve data for %s", species)
        return

    cdf = curves_dict[species]

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(cdf["year"], cdf["raw_cells_cumulative"],
            color="#2c7bb6", linewidth=2, label="Raw (observed)")
    ax.plot(cdf["year"], cdf["corrected_cells_cumulative"],
            color="#d7191c", linewidth=2, linestyle="--",
            label="Effort-corrected")
    ax.fill_between(
        cdf["year"],
        cdf["corrected_cells_cumulative"],
        cdf["raw_cells_cumulative"],
        alpha=0.15, color="#fdae61",
    )
    ax.set_xlabel("Year", fontsize=11)
    ax.set_ylabel("Cumulative occupied H3 cells", fontsize=11)
    ax.set_title(f"Range-fill curve: {species}", fontsize=12, style="italic")
    ax.legend(frameon=False, fontsize=9)
    ax.set_xlim(YEAR_MIN, YEAR_MAX)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()

    slug = species.replace(" ", "_").lower()
    out_path = output_dir / f"range_fill_{slug}.png"
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved range-fill plot: %s", out_path)


# ---------------------------------------------------------------------------
# 7. Plot: discovery map
# ---------------------------------------------------------------------------

def plot_discovery_map(df, novel_cells_df, species, h3_col, output_dir=None):
    """
    Map showing all occupied cells (gray) with novel detections highlighted
    in red.  Uses H3 cell centroids as scatter points.
    """
    if output_dir is None:
        output_dir = FIGURES_DIR / "study2"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    species_col = "species" if "species" in df.columns else "scientific_name"
    sp_df = df[df[species_col] == species]
    all_cells = sp_df[h3_col].unique()

    novel_sp = novel_cells_df[novel_cells_df["species"] == species]
    novel_set = set(novel_sp["h3_cell"])

    # Resolve centroids
    bg_lats, bg_lons = [], []
    nov_lats, nov_lons = [], []
    for cell in all_cells:
        lat, lon = h3.cell_to_latlng(cell)
        if cell in novel_set:
            nov_lats.append(lat)
            nov_lons.append(lon)
        else:
            bg_lats.append(lat)
            bg_lons.append(lon)

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(bg_lons, bg_lats, s=12, c="#bdbdbd", alpha=0.6,
               label="Previously known", edgecolors="none")
    if nov_lats:
        ax.scatter(nov_lons, nov_lats, s=28, c="#e31a1c", alpha=0.85,
                   label="Novel detection", edgecolors="black", linewidths=0.3)
    ax.set_xlabel("Longitude", fontsize=10)
    ax.set_ylabel("Latitude", fontsize=10)
    ax.set_title(f"Range expansion: {species}", fontsize=12, style="italic")
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()

    slug = species.replace(" ", "_").lower()
    out_path = output_dir / f"discovery_map_{slug}.png"
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved discovery map: %s", out_path)


# ---------------------------------------------------------------------------
# 8. Main pipeline
# ---------------------------------------------------------------------------

def run(h3_res=5):
    """Run the full Study 2 analysis pipeline."""
    logger.info("=== Study 2: Effort-Corrected Geographic Expansion ===")

    # Load
    df, cell_effort, h3_col = load_data()

    # Filter to study window
    df = df[(df["year"] >= YEAR_MIN) & (df["year"] <= YEAR_MAX)].copy()

    # Effort
    effort = calculate_effort(df, h3_col)

    # Rarefaction
    rarefied = rarefaction_correct(df, h3_col)
    rarefied_path = CLEANED_DIR / "study2_rarefied.parquet"
    rarefied.to_parquet(rarefied_path, index=False)
    logger.info("Saved rarefied table to %s", rarefied_path)

    # Range-fill curves (top 10 most-observed species)
    species_col = "species" if "species" in df.columns else "scientific_name"
    top_species = (
        df[species_col]
        .value_counts()
        .head(10)
        .index
        .tolist()
    )
    curves = range_fill_curves(df, h3_col, species_list=top_species)

    # Novel cell detection
    novel = detect_novel_cells(df, h3_col, recent_years=3)
    novel_path = CLEANED_DIR / "study2_novel_cells.parquet"
    if not novel.empty:
        novel.to_parquet(novel_path, index=False)
        logger.info("Saved novel cells to %s", novel_path)

    # Figures
    out_dir = FIGURES_DIR / "study2"
    for sp in top_species:
        plot_range_fill(curves, sp, output_dir=out_dir)
        plot_discovery_map(df, novel, sp, h3_col, output_dir=out_dir)

    logger.info("=== Study 2 complete ===")
    return {
        "effort": effort,
        "rarefied": rarefied,
        "curves": curves,
        "novel_cells": novel,
    }


if __name__ == "__main__":
    run(h3_res=H3_RES_BROAD)
