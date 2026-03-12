#!/usr/bin/env python3
"""
Run Study 2: Range expansion analysis for Plethodon species.

Analyzes temporal shifts in species occurrence across H3 hexagonal grid
cells to detect range expansion or contraction patterns.
"""
import argparse
import logging

from src.study2_range import analysis


def main():
    parser = argparse.ArgumentParser(
        description="Run Study 2 — Plethodon range expansion analysis",
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
