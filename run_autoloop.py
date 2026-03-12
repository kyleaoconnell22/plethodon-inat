#!/usr/bin/env python3
"""
Run the autoresearch loop for Study 4 color extraction optimization.

Usage:
    # On GCP VM after downloading photos:
    python run_autoloop.py --photo-dir /opt/plethodon/data/photos \
                           --validation-csv /opt/plethodon/data/cleaned/validation_subset.csv \
                           --n-iterations 200

    # Locally for testing:
    python run_autoloop.py --photo-dir data/photos \
                           --validation-csv data/cleaned/validation_subset.csv \
                           --n-iterations 10
"""
import argparse
import logging
import sys

import pandas as pd

sys.path.insert(0, ".")
from src.study4_color.autoloop import run_loop, DEFAULT_CONFIG


def main():
    parser = argparse.ArgumentParser(
        description="Autoresearch loop: optimize color extraction params"
    )
    parser.add_argument("--photo-dir", type=str, required=True)
    parser.add_argument("--validation-csv", type=str, required=True)
    parser.add_argument("--n-iterations", type=int, default=100)
    parser.add_argument("--exp-dir", type=str, default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    val_df = pd.read_csv(args.validation_csv)
    logging.info(f"Loaded validation set: {len(val_df)} observations")

    best_config, best_score = run_loop(
        photo_dir=args.photo_dir,
        validation_df=val_df,
        n_iterations=args.n_iterations,
        exp_dir=args.exp_dir,
        seed=args.seed,
    )

    print(f"\nBest score: {best_score:.6f}")
    print(f"Best config saved to: {args.exp_dir or 'data/experiments'}/best_config.json")


if __name__ == "__main__":
    main()
