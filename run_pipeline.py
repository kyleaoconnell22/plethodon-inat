#!/usr/bin/env python3
"""
Run the shared data pipeline: acquire, clean, and grid-assign Plethodon
iNaturalist observations.
"""
import argparse
import logging

from src.pipeline import acquire, clean, grid

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Run the Plethodon iNaturalist data pipeline",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume acquisition from the last checkpoint",
    )
    parser.add_argument(
        "--max-obs",
        type=int,
        default=None,
        help="Maximum observations to fetch (useful for testing)",
    )
    parser.add_argument(
        "--skip-acquire",
        action="store_true",
        help="Skip API acquisition and re-clean/re-grid existing raw data",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Step 1: Acquire
    if args.skip_acquire:
        logger.info("Skipping acquisition (--skip-acquire), loading existing raw data")
        df_raw = None  # clean.run() will load from disk
    else:
        logger.info("Step 1/3: Acquiring observations from iNaturalist API")
        df_raw = acquire.run(resume=args.resume, max_obs=args.max_obs)
        logger.info(f"  Acquired {len(df_raw)} raw observations")

    # Step 2: Clean
    logger.info("Step 2/3: Cleaning observations")
    df_clean = clean.run(df=df_raw)
    logger.info(f"  {len(df_clean)} observations after cleaning")

    # Step 3: Grid assignment
    logger.info("Step 3/3: Assigning H3 grid cells")
    df_gridded = grid.run(df=df_clean)

    # Summary
    n_obs = len(df_gridded)
    n_species = df_gridded["species"].nunique()
    year_min = df_gridded["year"].min()
    year_max = df_gridded["year"].max()

    print("\n" + "=" * 60)
    print("PIPELINE COMPLETE")
    print("=" * 60)
    print(f"  Observations : {n_obs:,}")
    print(f"  Species      : {n_species}")
    print(f"  Year range   : {year_min}-{year_max}")
    print(f"  Top species  :")
    top = df_gridded["species"].value_counts().head(10)
    for sp, count in top.items():
        print(f"    {sp:40s} {count:>6,}")
    print("=" * 60)


if __name__ == "__main__":
    main()
