"""
Spatial grid assignment using H3 hexagonal cells.

Assigns each observation to H3 cells at two resolutions:
- Resolution 5 (~252 km²): broad biogeographic patterns
- Resolution 7 (~5.2 km²): fine-scale population-level patterns

Also generates cell-level summary tables for downstream studies.
"""
import logging

import h3
import pandas as pd

from src.config import CLEANED_DIR, H3_RES_BROAD, H3_RES_FINE

logger = logging.getLogger(__name__)


def assign_h3_cells(df: pd.DataFrame) -> pd.DataFrame:
    """Add H3 cell IDs at broad and fine resolution."""
    logger.info(f"Assigning H3 cells (res {H3_RES_BROAD} and {H3_RES_FINE}) to {len(df)} obs")

    df[f"h3_res{H3_RES_BROAD}"] = df.apply(
        lambda row: h3.latlng_to_cell(row["lat"], row["lon"], H3_RES_BROAD), axis=1
    )
    df[f"h3_res{H3_RES_FINE}"] = df.apply(
        lambda row: h3.latlng_to_cell(row["lat"], row["lon"], H3_RES_FINE), axis=1
    )

    n_broad = df[f"h3_res{H3_RES_BROAD}"].nunique()
    n_fine = df[f"h3_res{H3_RES_FINE}"].nunique()
    logger.info(f"Unique cells: res{H3_RES_BROAD}={n_broad}, res{H3_RES_FINE}={n_fine}")

    return df


def build_cell_table(df: pd.DataFrame, h3_col: str) -> pd.DataFrame:
    """
    Build a summary table at the cell level.

    For each cell: species list, observation count, species richness,
    year range, centroid lat/lon.
    """
    cells = (
        df.groupby(h3_col)
        .agg(
            n_obs=("obs_id", "count"),
            n_species=("species", "nunique"),
            species_list=("species", lambda x: sorted(x.unique().tolist())),
            n_users=("user_id", "nunique"),
            year_min=("year", "min"),
            year_max=("year", "max"),
        )
        .reset_index()
    )

    # Add cell centroid coordinates
    cells["cell_lat"] = cells[h3_col].apply(lambda c: h3.cell_to_latlng(c)[0])
    cells["cell_lon"] = cells[h3_col].apply(lambda c: h3.cell_to_latlng(c)[1])

    return cells


def build_incidence_matrix(df: pd.DataFrame, h3_col: str) -> pd.DataFrame:
    """
    Build a species × cell presence/absence matrix.

    Used by Study 3 (co-occurrence) and Study 2 (range analysis).
    """
    incidence = (
        df.groupby([h3_col, "species"])["obs_id"]
        .count()
        .unstack(fill_value=0)
    )
    # Convert counts to presence/absence
    incidence = (incidence > 0).astype(int)
    return incidence


def run(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Run grid assignment and save outputs."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if df is None:
        df = pd.read_parquet(CLEANED_DIR / "plethodon_cleaned.parquet")

    df = assign_h3_cells(df)

    # Save observation table with grid assignments
    out_path = CLEANED_DIR / "plethodon_gridded.parquet"
    df.to_parquet(out_path, index=False)

    # Build and save cell summaries
    for res in [H3_RES_BROAD, H3_RES_FINE]:
        h3_col = f"h3_res{res}"
        cell_table = build_cell_table(df, h3_col)
        cell_path = CLEANED_DIR / f"cells_res{res}.parquet"
        cell_table.to_parquet(cell_path, index=False)
        logger.info(f"Saved cell table: {cell_path} ({len(cell_table)} cells)")

        incidence = build_incidence_matrix(df, h3_col)
        inc_path = CLEANED_DIR / f"incidence_res{res}.parquet"
        incidence.to_parquet(inc_path)
        logger.info(
            f"Saved incidence matrix: {inc_path} "
            f"({incidence.shape[0]} cells × {incidence.shape[1]} species)"
        )

    logger.info("Grid assignment complete")
    return df


if __name__ == "__main__":
    run()
