"""
Data acquisition: pull all Plethodon observations from iNaturalist API.

Uses pyinaturalist to paginate through all Research Grade observations
for genus Plethodon (taxon_id=17684). Extracts fields needed by all
three downstream studies and saves raw data as parquet + CSV.
"""
import json
import time
import logging
from pathlib import Path

import pandas as pd
from pyinaturalist import get_observations

from src.config import (
    INAT_TAXON_ID,
    INAT_PER_PAGE,
    INAT_RATE_LIMIT_DELAY,
    INAT_QUALITY_GRADE,
    RAW_DIR,
)

logger = logging.getLogger(__name__)


def _extract_obs_record(obs: dict) -> dict | None:
    """Extract a flat record from a single iNaturalist observation JSON."""
    taxon = obs.get("taxon")
    if not taxon:
        return None

    # Get species-level name
    species_name = taxon.get("name", "")
    # Skip sub-species level — keep genus + species only
    rank = taxon.get("rank", "")

    # Location
    loc = obs.get("location")
    if not loc:
        return None
    if isinstance(loc, str):
        parts = loc.split(",")
        lat, lon = float(parts[0]), float(parts[1])
    elif isinstance(loc, (list, tuple)):
        lat, lon = float(loc[0]), float(loc[1])
    else:
        return None

    # Photo URLs — first photo only for Study 4, all for reference
    photos = obs.get("photos", []) or obs.get("observation_photos", [])
    photo_urls = []
    for p in photos:
        if isinstance(p, dict):
            url = p.get("url") or p.get("photo", {}).get("url", "")
            if url:
                # Convert square thumbnail to medium size
                photo_urls.append(url.replace("square", "medium"))

    # ID agreement counts
    idents = obs.get("identifications", [])
    agreements = sum(1 for i in idents if i.get("category") == "supporting")
    disagreements = sum(1 for i in idents if i.get("category") == "maverick")

    return {
        "obs_id": obs.get("id"),
        "taxon_id": taxon.get("id"),
        "species": species_name,
        "rank": rank,
        "lat": lat,
        "lon": lon,
        "positional_accuracy": obs.get("positional_accuracy"),
        "observed_on": obs.get("observed_on"),
        "user_id": obs.get("user", {}).get("id"),
        "user_login": obs.get("user", {}).get("login"),
        "quality_grade": obs.get("quality_grade"),
        "num_id_agreements": agreements,
        "num_id_disagreements": disagreements,
        "photo_url_first": photo_urls[0] if photo_urls else None,
        "photo_urls": json.dumps(photo_urls),
        "geoprivacy": obs.get("geoprivacy"),
        "taxon_geoprivacy": obs.get("taxon_geoprivacy"),
        "obscured": obs.get("obscured", False),
    }


def fetch_all_plethodon(
    resume_from_id: int | None = None,
    max_obs: int | None = None,
) -> pd.DataFrame:
    """
    Fetch all Research Grade Plethodon observations from iNaturalist.

    Uses id_above pagination (most reliable for large result sets).
    Optionally resumes from a given observation ID for crash recovery.

    Parameters
    ----------
    resume_from_id : int, optional
        Resume pagination from this observation ID.
    max_obs : int, optional
        Stop after collecting this many observations (for testing).

    Returns
    -------
    pd.DataFrame
        Raw observation records.
    """
    records = []
    id_above = resume_from_id or 0
    page_num = 0
    total_fetched = 0

    logger.info(
        f"Starting iNaturalist fetch for taxon {INAT_TAXON_ID} "
        f"(quality_grade={INAT_QUALITY_GRADE})"
    )

    while True:
        page_num += 1
        try:
            response = get_observations(
                taxon_id=INAT_TAXON_ID,
                quality_grade=INAT_QUALITY_GRADE,
                per_page=INAT_PER_PAGE,
                order="asc",
                order_by="id",
                id_above=id_above,
            )
        except Exception as e:
            logger.error(f"API error on page {page_num} (id_above={id_above}): {e}")
            # Save progress checkpoint
            if records:
                _save_checkpoint(records, id_above)
            raise

        results = response.get("results", [])
        if not results:
            logger.info(f"No more results after page {page_num}")
            break

        for obs in results:
            record = _extract_obs_record(obs)
            if record:
                records.append(record)

        id_above = results[-1]["id"]
        total_fetched += len(results)

        if page_num % 10 == 0:
            logger.info(
                f"Page {page_num}: {total_fetched} obs fetched, "
                f"last id={id_above}, {len(records)} valid records"
            )

        # Save periodic checkpoint every 50 pages
        if page_num % 50 == 0 and records:
            _save_checkpoint(records, id_above)

        if max_obs and total_fetched >= max_obs:
            logger.info(f"Reached max_obs limit ({max_obs})")
            break

        time.sleep(INAT_RATE_LIMIT_DELAY)

    df = pd.DataFrame(records)
    logger.info(f"Fetch complete: {len(df)} records from {page_num} pages")
    return df


def _save_checkpoint(records: list[dict], last_id: int) -> None:
    """Save intermediate results for crash recovery."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    checkpoint_path = RAW_DIR / "checkpoint.parquet"
    df = pd.DataFrame(records)
    df.to_parquet(checkpoint_path, index=False)
    # Save last ID for resume
    (RAW_DIR / "checkpoint_last_id.txt").write_text(str(last_id))
    logger.info(f"Checkpoint saved: {len(df)} records, last_id={last_id}")


def save_raw_data(df: pd.DataFrame) -> tuple[Path, Path]:
    """Save raw data as parquet (primary) and CSV (human-readable)."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    parquet_path = RAW_DIR / "plethodon_raw.parquet"
    csv_path = RAW_DIR / "plethodon_raw.csv"

    df.to_parquet(parquet_path, index=False)
    df.to_csv(csv_path, index=False)

    logger.info(f"Raw data saved: {parquet_path} ({len(df)} rows)")
    return parquet_path, csv_path


def run(resume: bool = False, max_obs: int | None = None) -> pd.DataFrame:
    """Main entry point for data acquisition."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    resume_id = None
    if resume:
        id_file = RAW_DIR / "checkpoint_last_id.txt"
        if id_file.exists():
            resume_id = int(id_file.read_text().strip())
            logger.info(f"Resuming from id_above={resume_id}")

    df = fetch_all_plethodon(resume_from_id=resume_id, max_obs=max_obs)
    save_raw_data(df)
    return df


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Fetch Plethodon iNat observations")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--max-obs", type=int, default=None, help="Max observations")
    args = parser.parse_args()

    run(resume=args.resume, max_obs=args.max_obs)
