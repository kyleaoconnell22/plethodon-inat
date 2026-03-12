"""
Data cleaning pipeline for Plethodon observations.

Steps:
1. Remove observations with obscured/private coordinates
2. Filter to Research Grade only
3. Remove duplicates (same user, date, location within 100m)
4. Flag observations outside expected ranges (potential misIDs)
5. Standardize columns and types
"""
import logging

import numpy as np
import pandas as pd

from src.config import CLEANED_DIR, DUPLICATE_DISTANCE_M, RAW_DIR

logger = logging.getLogger(__name__)


def load_raw() -> pd.DataFrame:
    """Load raw data from parquet."""
    path = RAW_DIR / "plethodon_raw.parquet"
    df = pd.read_parquet(path)
    logger.info(f"Loaded {len(df)} raw records")
    return df


def remove_obscured(df: pd.DataFrame) -> pd.DataFrame:
    """Remove observations with obscured or private geoprivacy."""
    before = len(df)
    mask = (
        (df["geoprivacy"].isna() | (df["geoprivacy"] == "open"))
        & (df["taxon_geoprivacy"].isna() | (df["taxon_geoprivacy"] == "open"))
        & (~df["obscured"].fillna(False))
    )
    df = df[mask].copy()
    logger.info(f"Removed {before - len(df)} obscured/private obs ({len(df)} remain)")
    return df


def filter_research_grade(df: pd.DataFrame) -> pd.DataFrame:
    """Keep only Research Grade observations."""
    before = len(df)
    df = df[df["quality_grade"] == "research"].copy()
    logger.info(f"Filtered to Research Grade: {before - len(df)} removed ({len(df)} remain)")
    return df


def _haversine_m(lat1, lon1, lat2, lon2):
    """Vectorized haversine distance in meters."""
    R = 6_371_000  # Earth radius in meters
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a))


def remove_duplicates(df: pd.DataFrame, distance_m: float = DUPLICATE_DISTANCE_M) -> pd.DataFrame:
    """
    Remove duplicate observations: same user, same date, within distance_m.

    Uses a groupby on (user_id, observed_on) then checks pairwise distances
    within each group. Keeps the observation with the most ID agreements.
    """
    before = len(df)
    df = df.sort_values("num_id_agreements", ascending=False)

    # Group by user + date
    keep_mask = np.ones(len(df), dtype=bool)
    df_reset = df.reset_index(drop=True)

    for _, group in df_reset.groupby(["user_id", "observed_on"]):
        if len(group) < 2:
            continue
        idxs = group.index.tolist()
        for i, idx_i in enumerate(idxs):
            if not keep_mask[idx_i]:
                continue
            for idx_j in idxs[i + 1 :]:
                if not keep_mask[idx_j]:
                    continue
                dist = _haversine_m(
                    df_reset.at[idx_i, "lat"],
                    df_reset.at[idx_i, "lon"],
                    df_reset.at[idx_j, "lat"],
                    df_reset.at[idx_j, "lon"],
                )
                if dist < distance_m:
                    # Drop the one with fewer agreements (later in sorted order)
                    keep_mask[idx_j] = False

    df = df_reset[keep_mask].copy()
    logger.info(f"Removed {before - len(df)} duplicates ({len(df)} remain)")
    return df


def flag_out_of_range(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flag observations that may be outside expected species ranges.

    Uses a simple bounding-box approach based on known Plethodon distribution:
    genus is endemic to eastern North America + Pacific Northwest.
    More sophisticated range checks would use IUCN shapefiles.
    """
    # Plethodon is broadly distributed in:
    # Eastern NA: lat ~25-50, lon ~-90 to -65
    # Pacific NW (P. vehiculum, P. dunni, P. elongatus, etc.): lat ~38-50, lon ~-125 to -115
    eastern = (df["lat"].between(24, 52)) & (df["lon"].between(-92, -64))
    pacific_nw = (df["lat"].between(36, 52)) & (df["lon"].between(-126, -114))

    in_range = eastern | pacific_nw
    df["out_of_range_flag"] = ~in_range

    n_flagged = (~in_range).sum()
    if n_flagged > 0:
        logger.warning(f"Flagged {n_flagged} observations as potentially out of range")

    return df


def standardize_types(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure consistent dtypes for downstream analysis."""
    df["observed_on"] = pd.to_datetime(df["observed_on"], errors="coerce")
    df["year"] = df["observed_on"].dt.year
    df["month"] = df["observed_on"].dt.month

    for col in ["lat", "lon"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["positional_accuracy"] = pd.to_numeric(df["positional_accuracy"], errors="coerce")
    return df


def run(df: pd.DataFrame | None = None) -> pd.DataFrame:
    """Run full cleaning pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if df is None:
        df = load_raw()

    initial = len(df)

    df = remove_obscured(df)
    df = filter_research_grade(df)
    df = standardize_types(df)
    df = remove_duplicates(df)
    df = flag_out_of_range(df)

    # Drop rows with missing critical fields
    df = df.dropna(subset=["lat", "lon", "observed_on", "species"])
    logger.info(f"Cleaning complete: {initial} → {len(df)} observations")

    # Save
    CLEANED_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CLEANED_DIR / "plethodon_cleaned.parquet"
    df.to_parquet(out_path, index=False)
    df.to_csv(CLEANED_DIR / "plethodon_cleaned.csv", index=False)
    logger.info(f"Saved cleaned data to {out_path}")

    # Summary stats
    n_species = df["species"].nunique()
    year_range = f"{df['year'].min()}-{df['year'].max()}"
    logger.info(f"Summary: {len(df)} obs, {n_species} species, years {year_range}")

    return df


if __name__ == "__main__":
    run()
