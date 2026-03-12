#!/usr/bin/env python3
"""
Run Study 3: Co-occurrence analysis for Plethodon species pairs.

Tests for non-random spatial co-occurrence patterns between focal
Plethodon species pairs using null-model permutation tests on H3 cells.
"""
import argparse
import logging

from src.study3_cooccur import analysis


def main():
    parser = argparse.ArgumentParser(
        description="Run Study 3 — Plethodon co-occurrence analysis",
    )
    parser.add_argument(
        "--h3-res",
        type=int,
        default=5,
        help="H3 resolution for spatial binning (default: 5, ~252 km^2 cells)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    analysis.run(h3_res=args.h3_res)


if __name__ == "__main__":
    main()
