#!/usr/bin/env python3
"""
Run Study 4: Color/pattern variation analysis for Plethodon species.

Downloads observation photos, extracts color features from dorsal regions,
and analyzes geographic and temporal variation in color phenotypes.
"""
import argparse
import logging

from src.study4_color import analysis


def main():
    parser = argparse.ArgumentParser(
        description="Run Study 4 — Plethodon color variation analysis",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip photo download (use when photos are already cached locally)",
    )
    parser.add_argument(
        "--max-photos",
        type=int,
        default=None,
        help="Maximum number of photos to download (useful for testing)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    analysis.run(skip_download=args.skip_download, max_photos=args.max_photos)


if __name__ == "__main__":
    main()
