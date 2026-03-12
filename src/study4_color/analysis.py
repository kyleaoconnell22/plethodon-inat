"""
Study 4: Geographic Variation in Dorsal Color (Lightness/Darkness).

Analyzes dorsal brightness patterns across the Plethodon range using
iNaturalist photos. Downloads photos, extracts color metrics from a
central crop, and tests for geographic clines in brightness.
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import seaborn as sns
import statsmodels.api as sm
from PIL import Image
from scipy import stats
from skimage.color import rgb2hsv
from skimage.measure import shannon_entropy
from tqdm import tqdm

from src.config import (
    CLEANED_DIR,
    FIGURES_DIR,
    PHOTOS_DIR,
    PHOTO_DOWNLOAD_WORKERS,
    PHOTO_RATE_LIMIT_DELAY,
    CENTRAL_CROP_FRACTION,
    MIN_BRIGHTNESS,
    MAX_BRIGHTNESS,
    MIN_IMAGE_ENTROPY,
    H3_RES_BROAD,
)

logger = logging.getLogger(__name__)

STUDY_FIGURES_DIR = FIGURES_DIR / "study4_color"


# ── 1. Photo manifest ────────────────────────────────────────────────


def generate_photo_manifest(df: pd.DataFrame) -> pd.DataFrame:
    """Extract obs_id and first photo URL for records with valid photos."""
    logger.info(f"Generating photo manifest from {len(df)} observations")

    manifest = df[["obs_id", "photo_url_first"]].dropna(subset=["photo_url_first"]).copy()
    manifest = manifest.drop_duplicates(subset="obs_id").reset_index(drop=True)

    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = PHOTOS_DIR / "photo_manifest.csv"
    manifest.to_csv(manifest_path, index=False)
    logger.info(f"Saved manifest: {manifest_path} ({len(manifest)} photos)")

    return manifest


# ── 2. Photo download ────────────────────────────────────────────────


def _download_one(obs_id, url, output_dir, rate_limit):
    """Download a single photo. Returns (obs_id, local_path, status)."""
    local_path = output_dir / f"{obs_id}.jpg"
    if local_path.exists():
        return obs_id, str(local_path), "skipped"
    try:
        time.sleep(rate_limit)
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        local_path.write_bytes(resp.content)
        return obs_id, str(local_path), "ok"
    except Exception as e:
        logger.debug(f"Failed to download obs {obs_id}: {e}")
        return obs_id, None, f"error: {e}"


def download_photos(
    manifest_df: pd.DataFrame,
    output_dir: Path | str | None = None,
    max_workers: int = PHOTO_DOWNLOAD_WORKERS,
    rate_limit: float = PHOTO_RATE_LIMIT_DELAY,
) -> pd.DataFrame:
    """Download photos from the manifest using a thread pool."""
    if output_dir is None:
        output_dir = PHOTOS_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        f"Downloading {len(manifest_df)} photos "
        f"(workers={max_workers}, rate_limit={rate_limit}s)"
    )

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _download_one, row.obs_id, row.photo_url_first, output_dir, rate_limit
            ): row.obs_id
            for row in manifest_df.itertuples()
        }
        for future in tqdm(as_completed(futures), total=len(futures), desc="Downloading"):
            results.append(future.result())

    dl_df = pd.DataFrame(results, columns=["obs_id", "local_path", "download_status"])
    n_ok = (dl_df["download_status"] == "ok").sum()
    n_skip = (dl_df["download_status"] == "skipped").sum()
    n_err = dl_df["download_status"].str.startswith("error").sum()
    logger.info(f"Download complete: {n_ok} new, {n_skip} skipped, {n_err} errors")

    return dl_df


# ── 3. Single-image color extraction ─────────────────────────────────


def extract_color(
    image_path: str | Path,
    central_crop_fraction: float = CENTRAL_CROP_FRACTION,
) -> dict:
    """Extract color metrics from the central crop of an image."""
    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    arr = np.array(img)

    # Central crop
    cw = int(w * central_crop_fraction)
    ch = int(h * central_crop_fraction)
    x0 = (w - cw) // 2
    y0 = (h - ch) // 2
    crop = arr[y0 : y0 + ch, x0 : x0 + cw]

    # Convert to HSV (skimage expects float 0-1 input, returns 0-1 output)
    hsv = rgb2hsv(crop.astype(np.float64) / 255.0)
    h_chan = hsv[:, :, 0] * 360.0    # hue in degrees
    s_chan = hsv[:, :, 1] * 255.0    # saturation 0-255
    v_chan = hsv[:, :, 2] * 255.0    # brightness 0-255

    entropy = shannon_entropy(crop)

    return {
        "mean_brightness": float(np.mean(v_chan)),
        "mean_hue": float(np.mean(h_chan)),
        "mean_saturation": float(np.mean(s_chan)),
        "entropy": float(entropy),
        "width": w,
        "height": h,
    }


# ── 4. Batch color extraction ────────────────────────────────────────


def batch_extract_colors(
    photo_dir: Path | str | None = None,
    manifest_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run extract_color on all downloaded photos with QC filtering."""
    if photo_dir is None:
        photo_dir = PHOTOS_DIR
    photo_dir = Path(photo_dir)

    if manifest_df is None:
        manifest_df = pd.read_csv(PHOTOS_DIR / "photo_manifest.csv")

    records = []
    for row in tqdm(manifest_df.itertuples(), total=len(manifest_df), desc="Extracting color"):
        fpath = photo_dir / f"{row.obs_id}.jpg"
        if not fpath.exists():
            continue
        try:
            metrics = extract_color(fpath)
            metrics["obs_id"] = row.obs_id
            records.append(metrics)
        except Exception as e:
            logger.debug(f"Color extraction failed for {row.obs_id}: {e}")

    color_df = pd.DataFrame(records)
    logger.info(f"Extracted color from {len(color_df)} images")

    # Quality control
    color_df["passed_qc"] = (
        (color_df["mean_brightness"] >= MIN_BRIGHTNESS)
        & (color_df["mean_brightness"] <= MAX_BRIGHTNESS)
        & (color_df["entropy"] >= MIN_IMAGE_ENTROPY)
    )
    n_pass = color_df["passed_qc"].sum()
    n_fail = len(color_df) - n_pass
    logger.info(f"QC: {n_pass} passed, {n_fail} removed (dark/bright/low-entropy)")

    return color_df


# ── 5. Merge color + observation data ────────────────────────────────


def merge_color_with_observations(
    color_df: pd.DataFrame,
    obs_df: pd.DataFrame,
) -> pd.DataFrame:
    """Join color metrics to observation data (lat, lon, species, h3, year)."""
    qc_df = color_df[color_df["passed_qc"]].copy()
    merged = qc_df.merge(obs_df, on="obs_id", how="inner")
    logger.info(
        f"Merged color data: {len(merged)} obs "
        f"({merged['species'].nunique()} species)"
    )
    return merged


# ── 6. Geographic analysis ────────────────────────────────────────────


def _ols_summary(y, X, label):
    """Fit OLS and return a summary dict."""
    X = sm.add_constant(X)
    model = sm.OLS(y, X, missing="drop").fit()
    logger.info(f"OLS [{label}]: R²={model.rsquared:.3f}, n={int(model.nobs)}")
    return {
        "label": label,
        "rsquared": model.rsquared,
        "adj_rsquared": model.rsquared_adj,
        "f_pvalue": model.f_pvalue,
        "n": int(model.nobs),
        "params": model.params.to_dict(),
        "pvalues": model.pvalues.to_dict(),
        "summary_text": str(model.summary()),
    }


def geographic_analysis(merged_df: pd.DataFrame) -> dict:
    """
    Run geographic brightness analyses structured as:
      Primary:     within-species for P. cinereus (brightness ~ lat + lon)
      Secondary:   within-species for other well-sampled species
      Exploratory: cross-species comparison (are higher-lat species darker/lighter?)
    """
    h3_col = f"h3_res{H3_RES_BROAD}"
    results = {}
    MIN_N_FOR_REGRESSION = 50

    # ── Cell-level brightness summary ────────────────────────────────
    cell_brightness = (
        merged_df.groupby(h3_col)
        .agg(
            mean_brightness=("mean_brightness", "mean"),
            n_photos=("obs_id", "count"),
            n_species=("species", "nunique"),
            cell_lat=("lat", "mean"),
            cell_lon=("lon", "mean"),
        )
        .reset_index()
    )
    results["cell_brightness"] = cell_brightness
    logger.info(f"Cell-level brightness: {len(cell_brightness)} cells")

    # ── PRIMARY: P. cinereus within-species ──────────────────────────
    logger.info("=" * 50)
    logger.info("PRIMARY ANALYSIS: P. cinereus within-species")
    pc = merged_df[merged_df["species"] == "Plethodon cinereus"]
    if len(pc) >= MIN_N_FOR_REGRESSION:
        results["primary_ols_cinereus"] = _ols_summary(
            pc["mean_brightness"],
            pc[["lat", "lon"]],
            "PRIMARY: P_cinereus ~ lat + lon",
        )
        # Also test latitude alone (cleaner test of ecogeographic hypotheses)
        results["primary_ols_cinereus_lat_only"] = _ols_summary(
            pc["mean_brightness"],
            pc[["lat"]],
            "PRIMARY: P_cinereus ~ lat",
        )
        # Cell-level for P. cinereus (reduces pseudoreplication)
        pc_cells = (
            pc.groupby(h3_col)
            .agg(
                mean_brightness=("mean_brightness", "mean"),
                n=("obs_id", "count"),
                cell_lat=("lat", "mean"),
                cell_lon=("lon", "mean"),
            )
            .reset_index()
        )
        pc_cells_filtered = pc_cells[pc_cells["n"] >= 3]
        if len(pc_cells_filtered) >= 20:
            results["primary_ols_cinereus_cell_level"] = _ols_summary(
                pc_cells_filtered["mean_brightness"],
                pc_cells_filtered[["cell_lat", "cell_lon"]],
                "PRIMARY: P_cinereus cell-level ~ lat + lon",
            )
        logger.info(f"  P. cinereus: {len(pc)} obs, {len(pc_cells)} cells")
    else:
        logger.warning(f"Too few P. cinereus obs ({len(pc)}) for primary analysis")
        results["primary_ols_cinereus"] = None

    # ── SECONDARY: Other well-sampled species ────────────────────────
    logger.info("=" * 50)
    logger.info("SECONDARY ANALYSIS: Within-species for other species")
    secondary_species = (
        merged_df[merged_df["species"] != "Plethodon cinereus"]
        .groupby("species")
        .size()
        .loc[lambda x: x >= MIN_N_FOR_REGRESSION]
        .sort_values(ascending=False)
        .index.tolist()
    )
    results["secondary_within_species"] = {}
    for sp in secondary_species:
        sp_df = merged_df[merged_df["species"] == sp]
        result = _ols_summary(
            sp_df["mean_brightness"],
            sp_df[["lat", "lon"]],
            f"SECONDARY: {sp} ~ lat + lon",
        )
        results["secondary_within_species"][sp] = result
    logger.info(f"  {len(secondary_species)} species with n >= {MIN_N_FOR_REGRESSION}")

    # ── EXPLORATORY: Cross-species comparison ────────────────────────
    logger.info("=" * 50)
    logger.info("EXPLORATORY: Cross-species brightness comparison")

    # Kruskal-Wallis: do species differ in brightness?
    species_groups = [
        grp["mean_brightness"].values
        for _, grp in merged_df.groupby("species")
        if len(grp) >= 10
    ]
    if len(species_groups) >= 2:
        kw_stat, kw_p = stats.kruskal(*species_groups)
        results["exploratory_kruskal_wallis"] = {"statistic": kw_stat, "pvalue": kw_p}
        logger.info(f"  Kruskal-Wallis across species: H={kw_stat:.1f}, p={kw_p:.2e}")
    else:
        results["exploratory_kruskal_wallis"] = None

    # Species-level: does mean brightness correlate with mean latitude?
    sp_summary = (
        merged_df.groupby("species")
        .agg(
            n=("obs_id", "count"),
            mean_brightness=("mean_brightness", "mean"),
            std_brightness=("mean_brightness", "std"),
            mean_lat=("lat", "mean"),
            lat_range=("lat", lambda x: x.max() - x.min()),
        )
        .sort_values("n", ascending=False)
        .reset_index()
    )
    results["species_summary"] = sp_summary

    # Correlation of species mean brightness vs species mean latitude
    sp_with_enough = sp_summary[sp_summary["n"] >= 10]
    if len(sp_with_enough) >= 5:
        r, p = stats.pearsonr(sp_with_enough["mean_lat"], sp_with_enough["mean_brightness"])
        results["exploratory_species_lat_brightness_corr"] = {
            "r": round(r, 4), "p": round(p, 4), "n_species": len(sp_with_enough),
        }
        logger.info(f"  Species mean brightness vs mean latitude: r={r:.3f}, p={p:.3f}, n={len(sp_with_enough)} species")

    return results


# ── 7. Brightness map ────────────────────────────────────────────────


def plot_brightness_map(
    merged_df: pd.DataFrame,
    h3_col: str | None = None,
    output_dir: Path | str | None = None,
) -> Path:
    """Map of mean dorsal brightness across the Plethodon range."""
    if h3_col is None:
        h3_col = f"h3_res{H3_RES_BROAD}"
    if output_dir is None:
        output_dir = STUDY_FIGURES_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    import h3 as h3lib

    cell_stats = (
        merged_df.groupby(h3_col)
        .agg(mean_brightness=("mean_brightness", "mean"), n=("obs_id", "count"))
        .reset_index()
    )
    cell_stats["cell_lat"] = cell_stats[h3_col].apply(lambda c: h3lib.cell_to_latlng(c)[0])
    cell_stats["cell_lon"] = cell_stats[h3_col].apply(lambda c: h3lib.cell_to_latlng(c)[1])

    fig, ax = plt.subplots(figsize=(12, 8))
    sc = ax.scatter(
        cell_stats["cell_lon"],
        cell_stats["cell_lat"],
        c=cell_stats["mean_brightness"],
        cmap="cividis",
        s=cell_stats["n"].clip(upper=100) * 2,
        alpha=0.8,
        edgecolors="0.3",
        linewidths=0.3,
    )
    cbar = plt.colorbar(sc, ax=ax, label="Mean dorsal brightness (V)")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title("Geographic Variation in Plethodon Dorsal Brightness")
    ax.set_aspect("equal")
    fig.tight_layout()

    out_path = output_dir / "brightness_map.png"
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Saved brightness map: {out_path}")
    return out_path


# ── 8. Regression plots ──────────────────────────────────────────────


def plot_brightness_regressions(
    merged_df: pd.DataFrame,
    output_dir: Path | str | None = None,
) -> Path:
    """
    Multi-panel regression figure structured by analysis hierarchy:
      Top row:    PRIMARY — P. cinereus brightness vs latitude and longitude
      Bottom row: SECONDARY — within-species slopes for other well-sampled species
    """
    if output_dir is None:
        output_dir = STUDY_FIGURES_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    pc = merged_df[merged_df["species"] == "Plethodon cinereus"]

    fig, axes = plt.subplots(2, 2, figsize=(13, 11))

    # ── Top row: PRIMARY — P. cinereus ──────────────────────────────
    if not pc.empty:
        # Brightness vs latitude
        ax = axes[0, 0]
        sns.regplot(
            x="lat", y="mean_brightness", data=pc,
            scatter_kws={"alpha": 0.12, "s": 6, "color": "#2c7bb6"},
            line_kws={"color": "crimson", "linewidth": 2},
            ci=95, ax=ax,
        )
        r, p = stats.pearsonr(pc["lat"].dropna(), pc["mean_brightness"].dropna())
        ax.set_title(f"PRIMARY: P. cinereus (n={len(pc):,})\nr={r:.3f}, p={p:.2e}")
        ax.set_xlabel("Latitude")
        ax.set_ylabel("Mean dorsal brightness (L*)")

        # Brightness vs longitude
        ax = axes[0, 1]
        sns.regplot(
            x="lon", y="mean_brightness", data=pc,
            scatter_kws={"alpha": 0.12, "s": 6, "color": "#2c7bb6"},
            line_kws={"color": "navy", "linewidth": 2},
            ci=95, ax=ax,
        )
        r, p = stats.pearsonr(pc["lon"].dropna(), pc["mean_brightness"].dropna())
        ax.set_title(f"PRIMARY: P. cinereus (n={len(pc):,})\nr={r:.3f}, p={p:.2e}")
        ax.set_xlabel("Longitude (elevation proxy)")
        ax.set_ylabel("Mean dorsal brightness (L*)")

    # ── Bottom left: SECONDARY — within-species latitude slopes ─────
    ax = axes[1, 0]
    MIN_N = 50
    secondary = (
        merged_df.groupby("species")
        .filter(lambda g: len(g) >= MIN_N and g.name != "Plethodon cinereus")
    )
    species_slopes = []
    for sp, grp in secondary.groupby("species"):
        slope, _, r_value, p_value, _ = stats.linregress(grp["lat"], grp["mean_brightness"])
        species_slopes.append({
            "species": sp.replace("Plethodon ", "P. "),
            "slope": slope, "r": r_value, "p": p_value, "n": len(grp),
        })
    if species_slopes:
        slopes_df = pd.DataFrame(species_slopes).sort_values("slope")
        colors = ["#d7191c" if s < 0 else "#2c7bb6" for s in slopes_df["slope"]]
        ax.barh(slopes_df["species"], slopes_df["slope"], color=colors, edgecolor="0.3", linewidth=0.5)
        ax.axvline(0, color="black", linewidth=0.8, linestyle="--")
        ax.set_xlabel("Slope (brightness ~ latitude)")
        ax.set_title(f"SECONDARY: Within-species latitude slopes\n(species with n ≥ {MIN_N})")
        # Add significance markers
        for i, row in enumerate(slopes_df.itertuples()):
            if row.p < 0.05:
                ax.text(row.slope, i, " *", va="center", fontsize=10, fontweight="bold")

    # ── Bottom right: EXPLORATORY — species mean brightness vs lat ──
    ax = axes[1, 1]
    sp_means = (
        merged_df.groupby("species")
        .agg(mean_brightness=("mean_brightness", "mean"), mean_lat=("lat", "mean"), n=("obs_id", "count"))
        .reset_index()
    )
    sp_means = sp_means[sp_means["n"] >= 10]
    sp_means["short"] = sp_means["species"].str.replace("Plethodon ", "P. ")
    ax.scatter(sp_means["mean_lat"], sp_means["mean_brightness"],
               s=sp_means["n"].clip(upper=500) / 5, alpha=0.7, color="#fdae61", edgecolors="0.3")
    for _, row in sp_means.iterrows():
        ax.annotate(row["short"], (row["mean_lat"], row["mean_brightness"]),
                     fontsize=6, alpha=0.7, ha="center", va="bottom")
    if len(sp_means) >= 5:
        r, p = stats.pearsonr(sp_means["mean_lat"], sp_means["mean_brightness"])
        # Add regression line
        z = np.polyfit(sp_means["mean_lat"], sp_means["mean_brightness"], 1)
        x_line = np.linspace(sp_means["mean_lat"].min(), sp_means["mean_lat"].max(), 50)
        ax.plot(x_line, np.polyval(z, x_line), "k--", linewidth=1.5, alpha=0.5)
        ax.set_title(f"EXPLORATORY: Species means\nr={r:.3f}, p={p:.3f}, n={len(sp_means)} species")
    else:
        ax.set_title("EXPLORATORY: Species means")
    ax.set_xlabel("Mean latitude of species")
    ax.set_ylabel("Mean dorsal brightness (L*)")

    fig.suptitle("Dorsal Brightness vs. Geography — Analysis Hierarchy", fontsize=14, y=1.02)
    fig.tight_layout()

    out_path = output_dir / "brightness_regressions.png"
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Saved regression plots: {out_path}")
    return out_path


# ── 9. Species comparison ────────────────────────────────────────────


def plot_species_comparison(
    merged_df: pd.DataFrame,
    output_dir: Path | str | None = None,
) -> Path:
    """Box/violin plot of brightness distribution for top 15 species."""
    if output_dir is None:
        output_dir = STUDY_FIGURES_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    top_species = (
        merged_df["species"]
        .value_counts()
        .head(15)
        .index.tolist()
    )
    plot_df = merged_df[merged_df["species"].isin(top_species)].copy()
    plot_df["species_short"] = plot_df["species"].str.replace("Plethodon ", "P. ")

    # Order by median brightness
    order = (
        plot_df.groupby("species_short")["mean_brightness"]
        .median()
        .sort_values()
        .index.tolist()
    )

    fig, ax = plt.subplots(figsize=(10, 7))
    sns.violinplot(
        data=plot_df, y="species_short", x="mean_brightness",
        order=order, inner="box", scale="width",
        palette="coolwarm", ax=ax,
    )
    ax.set_xlabel("Mean dorsal brightness (V)")
    ax.set_ylabel("")
    ax.set_title(f"Dorsal Brightness by Species (top {len(top_species)})")
    fig.tight_layout()

    out_path = output_dir / "species_brightness_comparison.png"
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Saved species comparison: {out_path}")
    return out_path


# ── 10. Main entry point ─────────────────────────────────────────────


def run(skip_download: bool = False, max_photos: int | None = None) -> dict:
    """Run the full Study 4 pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logger.info("=== Study 4: Dorsal Color Analysis ===")

    # Load gridded observations
    obs_df = pd.read_parquet(CLEANED_DIR / "plethodon_gridded.parquet")
    logger.info(f"Loaded {len(obs_df)} gridded observations")

    # Step 1 — manifest
    manifest = generate_photo_manifest(obs_df)
    if max_photos:
        manifest = manifest.head(max_photos)
        logger.info(f"Limiting to {max_photos} photos")

    # Step 2 — download
    if skip_download:
        logger.info("Skipping photo download (--skip-download)")
        dl_df = None
    else:
        dl_df = download_photos(manifest)

    # Step 3 & 4 — extract color
    color_df = batch_extract_colors(PHOTOS_DIR, manifest)

    # Step 5 — merge
    merged = merge_color_with_observations(color_df, obs_df)

    # Step 6 — analysis
    results = geographic_analysis(merged)

    # Save key tables
    STUDY_FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(CLEANED_DIR / "study4_color_merged.parquet", index=False)
    results["species_summary"].to_csv(
        STUDY_FIGURES_DIR / "species_brightness_summary.csv", index=False
    )
    results["cell_brightness"].to_csv(
        STUDY_FIGURES_DIR / "cell_brightness.csv", index=False
    )
    logger.info("Saved analysis tables")

    # Steps 7-9 — figures
    plot_brightness_map(merged)
    plot_brightness_regressions(merged)
    plot_species_comparison(merged)

    logger.info("=== Study 4 complete ===")
    return results


if __name__ == "__main__":
    run()
