"""
Autoresearch loop for Study 4: Dorsal Color Extraction Optimization.

Inspired by Karpathy's autoresearch pattern: propose parameter change →
run experiment → measure metric → keep/revert → repeat.

The loop optimizes color extraction parameters to maximize geographic
signal (R² of brightness ~ latitude) while minimizing photo noise
(within-cell brightness variance).
"""
import copy
import json
import logging
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from PIL import Image
from scipy import stats
from skimage.color import rgb2hsv, rgb2lab
from skimage.exposure import equalize_hist
from skimage.measure import shannon_entropy

logger = logging.getLogger(__name__)


def _json_convert(obj):
    """Convert numpy types for JSON serialization."""
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


# ── Default extraction config ───────────────────────────────────────

DEFAULT_CONFIG = {
    "central_crop_fraction": 0.4,
    "color_space": "hsv",           # hsv, lab, rgb
    "crop_strategy": "center",      # center, upper_third, lower_third, adaptive
    "normalize_brightness": False,
    "background_mask_method": "none",  # none, green_threshold, saturation_threshold, dark_threshold
    "background_mask_threshold": 0.3,
    "min_brightness": 15,
    "max_brightness": 245,
    "min_entropy": 4.0,
    "percentile_trim": 0.0,        # trim extreme values before averaging
}

# ── Parameter bounds (for random proposals) ─────────────────────────

PARAM_BOUNDS = {
    "central_crop_fraction": ("float", 0.15, 0.7),
    "color_space": ("choice", ["hsv", "lab", "rgb"]),
    "crop_strategy": ("choice", ["center", "upper_third", "lower_third", "adaptive"]),
    "normalize_brightness": ("choice", [True, False]),
    "background_mask_method": ("choice", ["none", "green_threshold", "saturation_threshold", "dark_threshold"]),
    "background_mask_threshold": ("float", 0.1, 0.8),
    "min_brightness": ("int", 5, 50),
    "max_brightness": ("int", 200, 255),
    "min_entropy": ("float", 2.0, 6.0),
    "percentile_trim": ("float", 0.0, 0.10),
}


# ── Color extraction with configurable params ──────────────────────


def _get_crop_region(w, h, config):
    """Return (x0, y0, x1, y1) for the crop region."""
    frac = config["central_crop_fraction"]
    cw = int(w * frac)
    ch = int(h * frac)

    strategy = config["crop_strategy"]
    if strategy == "center":
        x0 = (w - cw) // 2
        y0 = (h - ch) // 2
    elif strategy == "upper_third":
        x0 = (w - cw) // 2
        y0 = int(h * 0.1)  # upper region
    elif strategy == "lower_third":
        x0 = (w - cw) // 2
        y0 = int(h * 0.55)  # lower region
    elif strategy == "adaptive":
        # Use center but with tighter crop
        x0 = (w - cw) // 2
        y0 = (h - ch) // 2
    else:
        x0 = (w - cw) // 2
        y0 = (h - ch) // 2

    return x0, y0, x0 + cw, y0 + ch


def _apply_background_mask(crop_arr, config):
    """Apply background masking, return masked pixel array or original."""
    method = config["background_mask_method"]
    threshold = config["background_mask_threshold"]

    if method == "none":
        return crop_arr

    # Convert to float for HSV analysis
    hsv = rgb2hsv(crop_arr.astype(np.float64) / 255.0)

    if method == "green_threshold":
        # Mask out green-ish pixels (leaves, moss)
        # Green hue ~0.2-0.45 in skimage HSV (0-1 scale)
        green_mask = (hsv[:, :, 0] > 0.15) & (hsv[:, :, 0] < 0.45) & (hsv[:, :, 1] > threshold)
        keep = ~green_mask
    elif method == "saturation_threshold":
        # Keep only pixels with sufficient saturation (likely salamander, not gray background)
        keep = hsv[:, :, 1] > threshold
    elif method == "dark_threshold":
        # Keep darker pixels (salamanders are generally dark)
        keep = hsv[:, :, 2] < (1.0 - threshold)
    else:
        return crop_arr

    # Need at least 10% of pixels to survive masking
    if keep.sum() < 0.1 * keep.size:
        return crop_arr

    # Return only kept pixels as 2D array (N, 3)
    return crop_arr[keep]


def _get_brightness(pixels, config):
    """Extract brightness value from pixel array using configured color space."""
    color_space = config["color_space"]

    if pixels.ndim == 3:
        # Standard image array (H, W, 3)
        flat = pixels.reshape(-1, 3).astype(np.float64) / 255.0
    elif pixels.ndim == 2:
        # Already flattened from masking (N, 3)
        flat = pixels.astype(np.float64) / 255.0
    else:
        return None

    if len(flat) == 0:
        return None

    if color_space == "hsv":
        from skimage.color import rgb2hsv as _rgb2hsv
        # rgb2hsv expects (M, N, 3), reshape
        hsv = _rgb2hsv(flat.reshape(1, -1, 3))
        values = hsv[0, :, 2] * 255.0  # V channel, 0-255
    elif color_space == "lab":
        lab = rgb2lab(flat.reshape(1, -1, 3))
        values = lab[0, :, 0]  # L channel, 0-100
    elif color_space == "rgb":
        # Simple luminance: 0.299*R + 0.587*G + 0.114*B
        values = (flat[:, 0] * 0.299 + flat[:, 1] * 0.587 + flat[:, 2] * 0.114) * 255.0
    else:
        return None

    # Percentile trimming
    trim = config["percentile_trim"]
    if trim > 0 and len(values) > 10:
        lo = np.percentile(values, trim * 100)
        hi = np.percentile(values, (1 - trim) * 100)
        values = values[(values >= lo) & (values <= hi)]

    return float(np.mean(values)) if len(values) > 0 else None


def extract_with_config(image_path, config):
    """Extract color from a single image using the given config."""
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception:
        return None

    w, h = img.size
    arr = np.array(img)

    # Optional brightness normalization
    if config["normalize_brightness"]:
        # Apply histogram equalization per channel
        for c in range(3):
            arr[:, :, c] = (equalize_hist(arr[:, :, c]) * 255).astype(np.uint8)

    # Crop
    x0, y0, x1, y1 = _get_crop_region(w, h, config)
    crop = arr[y0:y1, x0:x1]

    if crop.size == 0:
        return None

    # Entropy check (on original crop, before masking)
    entropy = shannon_entropy(crop)
    if entropy < config["min_entropy"]:
        return None

    # Background masking
    pixels = _apply_background_mask(crop, config)

    # Extract brightness
    brightness = _get_brightness(pixels, config)
    if brightness is None:
        return None

    # QC brightness bounds
    if brightness < config["min_brightness"] or brightness > config["max_brightness"]:
        return None

    return {
        "brightness": brightness,
        "entropy": entropy,
    }


# ── Experiment evaluation ───────────────────────────────────────────


def run_experiment(photo_dir, validation_df, config):
    """
    Run extraction with given config on validation photos.

    Parameters
    ----------
    photo_dir : Path
        Directory containing downloaded photos as {obs_id}.jpg
    validation_df : pd.DataFrame
        Must have columns: obs_id, lat, lon, h3_res5 (or similar h3 col)
    config : dict
        Extraction configuration

    Returns
    -------
    dict with keys: score, r_squared, within_cell_var, n_extracted, config
    """
    photo_dir = Path(photo_dir)
    results = []

    for row in validation_df.itertuples():
        fpath = photo_dir / f"{row.obs_id}.jpg"
        if not fpath.exists():
            continue
        extracted = extract_with_config(fpath, config)
        if extracted is not None:
            results.append({
                "obs_id": row.obs_id,
                "lat": row.lat,
                "lon": row.lon,
                "h3_cell": getattr(row, "h3_res5", None),
                "brightness": extracted["brightness"],
            })

    if len(results) < 30:
        return {"score": -999, "r_squared": 0, "within_cell_var": 999,
                "n_extracted": len(results), "config": config}

    df = pd.DataFrame(results)

    # R² of brightness ~ latitude
    slope, intercept, r_value, p_value, std_err = stats.linregress(df["lat"], df["brightness"])
    r_squared = r_value ** 2

    # Within-cell brightness variance (mean across cells with >= 3 obs)
    if df["h3_cell"].notna().any():
        cell_vars = df.groupby("h3_cell")["brightness"].var().dropna()
        cell_vars = cell_vars[df.groupby("h3_cell").size() >= 3]
        within_cell_var = cell_vars.mean() if len(cell_vars) > 0 else 0
    else:
        within_cell_var = df["brightness"].var()

    # Composite score
    lam = 0.5
    # Normalize within_cell_var to 0-1 range (assume max ~2000 for brightness variance)
    norm_var = min(within_cell_var / 2000.0, 1.0)
    score = r_squared - lam * norm_var

    return {
        "score": round(score, 6),
        "r_squared": round(r_squared, 6),
        "r_value": round(r_value, 4),
        "p_value": round(p_value, 6),
        "slope": round(slope, 4),
        "within_cell_var": round(within_cell_var, 2),
        "n_extracted": len(df),
        "n_passed_qc_pct": round(len(df) / len(validation_df) * 100, 1),
        "mean_brightness": round(df["brightness"].mean(), 2),
        "config": config,
    }


# ── Parameter proposal ──────────────────────────────────────────────


def propose_change(current_config, rng=None):
    """
    Propose a single-parameter change to the config.

    Changes ONE parameter at a time (isolation principle from program.md).
    Returns (new_config, change_description).
    """
    if rng is None:
        rng = np.random.default_rng()

    new_config = copy.deepcopy(current_config)
    param = rng.choice(list(PARAM_BOUNDS.keys()))
    bounds = PARAM_BOUNDS[param]

    old_val = new_config[param]

    if bounds[0] == "float":
        lo, hi = bounds[1], bounds[2]
        new_val = round(rng.uniform(lo, hi), 3)
    elif bounds[0] == "int":
        lo, hi = bounds[1], bounds[2]
        new_val = int(rng.integers(lo, hi + 1))
    elif bounds[0] == "choice":
        options = [o for o in bounds[1] if o != old_val]
        new_val = rng.choice(options) if options else old_val

    new_config[param] = new_val
    desc = f"{param}: {old_val} → {new_val}"
    return new_config, desc


# ── Experiment logging ──────────────────────────────────────────────


def log_experiment(exp_dir, iteration, result, change_desc, accepted):
    """Log a single experiment to the experiments directory."""
    exp_dir = Path(exp_dir)
    exp_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "iteration": iteration,
        "timestamp": datetime.now().isoformat(),
        "change": change_desc,
        "accepted": accepted,
        "score": result["score"],
        "r_squared": result["r_squared"],
        "r_value": result.get("r_value"),
        "p_value": result.get("p_value"),
        "slope": result.get("slope"),
        "within_cell_var": result["within_cell_var"],
        "n_extracted": result["n_extracted"],
        "n_passed_qc_pct": result.get("n_passed_qc_pct"),
        "mean_brightness": result.get("mean_brightness"),
        "config": result["config"],
    }

    # Append to JSONL log
    log_path = exp_dir / "experiments.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, default=_json_convert) + "\n")

    # Update best config if accepted
    if accepted:
        best_path = exp_dir / "best_config.json"
        with open(best_path, "w") as f:
            json.dump(result["config"], f, indent=2, default=_json_convert)

    return entry


def load_experiment_log(exp_dir):
    """Load all experiments from the log."""
    log_path = Path(exp_dir) / "experiments.jsonl"
    if not log_path.exists():
        return []
    entries = []
    with open(log_path) as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    return entries


# ── Main loop ───────────────────────────────────────────────────────


def run_loop(
    photo_dir,
    validation_df,
    n_iterations=100,
    exp_dir=None,
    initial_config=None,
    seed=42,
):
    """
    Run the autoresearch optimization loop.

    Parameters
    ----------
    photo_dir : str or Path
        Directory with downloaded photos ({obs_id}.jpg)
    validation_df : pd.DataFrame
        Validation subset with obs_id, lat, lon, h3_res5
    n_iterations : int
        Number of experiments to run
    exp_dir : str or Path
        Directory for experiment logs (default: photo_dir/../experiments)
    initial_config : dict
        Starting config (default: DEFAULT_CONFIG)
    seed : int
        Random seed for reproducibility
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
    )

    photo_dir = Path(photo_dir)
    if exp_dir is None:
        exp_dir = photo_dir.parent / "experiments"
    exp_dir = Path(exp_dir)
    exp_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(seed)
    config = copy.deepcopy(initial_config or DEFAULT_CONFIG)

    # Baseline experiment
    logger.info("Running baseline experiment with default config...")
    baseline = run_experiment(photo_dir, validation_df, config)
    best_score = baseline["score"]
    log_experiment(exp_dir, 0, baseline, "baseline", True)

    logger.info(
        f"Baseline: score={best_score:.6f}, R²={baseline['r_squared']:.6f}, "
        f"within_cell_var={baseline['within_cell_var']:.2f}, "
        f"n_extracted={baseline['n_extracted']}"
    )

    accepted_count = 0

    for i in range(1, n_iterations + 1):
        # Propose change
        new_config, change_desc = propose_change(config, rng)

        # Run experiment
        result = run_experiment(photo_dir, validation_df, new_config)

        # Accept or reject
        if result["score"] > best_score:
            accepted = True
            config = new_config
            improvement = result["score"] - best_score
            best_score = result["score"]
            accepted_count += 1
            status = f"ACCEPTED (+{improvement:.6f})"
        else:
            accepted = False
            delta = result["score"] - best_score
            status = f"rejected ({delta:.6f})"

        log_experiment(exp_dir, i, result, change_desc, accepted)

        logger.info(
            f"[{i}/{n_iterations}] {change_desc} → "
            f"score={result['score']:.6f} {status} "
            f"(R²={result['r_squared']:.6f}, var={result['within_cell_var']:.1f}, "
            f"n={result['n_extracted']})"
        )

    # Summary
    logger.info("=" * 60)
    logger.info(f"AUTORESEARCH COMPLETE: {n_iterations} experiments")
    logger.info(f"  Accepted: {accepted_count}/{n_iterations} ({accepted_count/n_iterations*100:.1f}%)")
    logger.info(f"  Best score: {best_score:.6f}")
    logger.info(f"  Best config: {json.dumps(config, indent=2, default=_json_convert)}")
    logger.info(f"  Logs: {exp_dir / 'experiments.jsonl'}")
    logger.info("=" * 60)

    return config, best_score


# ── CLI entry point ─────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Autoresearch loop for color extraction")
    parser.add_argument("--photo-dir", type=str, required=True, help="Directory with photos")
    parser.add_argument("--validation-csv", type=str, required=True, help="CSV with obs_id, lat, lon, h3_res5")
    parser.add_argument("--n-iterations", type=int, default=100, help="Number of experiments")
    parser.add_argument("--exp-dir", type=str, default=None, help="Experiment log directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    val_df = pd.read_csv(args.validation_csv)
    best_config, best_score = run_loop(
        photo_dir=args.photo_dir,
        validation_df=val_df,
        n_iterations=args.n_iterations,
        exp_dir=args.exp_dir,
        seed=args.seed,
    )
