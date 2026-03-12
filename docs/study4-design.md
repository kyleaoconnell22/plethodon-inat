# Study 4: Dorsal Color Variation with Autoresearch Loop

**Date**: 2026-03-12
**Status**: Running on GCP

## Goal
Determine whether dorsal lightness/darkness in *Plethodon* varies predictably with latitude, elevation, or climate (Gloger's rule vs. thermal melanism hypothesis) using iNaturalist photos and an automated parameter optimization loop.

## Architecture

### Compute
- **Local (MacBook, Apple Silicon)**: Data acquisition from iNat API, cleaning, H3 grid assignment, photo manifest generation, final geographic analysis + publication figures
- **GCP VM**: Photo download (103K photos), autoresearch loop (200 iterations), final color extraction on all photos, results upload to GCS

### Autoresearch Loop (runs on GCP VM)
1. `program.md` defines high-level optimization goal
2. Random single-parameter perturbation proposed to `extract_config` dict
3. Run extraction on validation subset (1,000 photos, stratified across species/geography)
4. Measure composite score: `R²(brightness ~ latitude) - 0.5 × mean(within_cell_variance)`
5. If score > best: keep config. Else: revert.
6. Log experiment to `experiments/experiments.jsonl`
7. Repeat for 200 iterations

### What the loop tunes
- `central_crop_fraction`: 0.15–0.7 (fraction of image to keep, centered)
- `color_space`: HSV, LAB, RGB
- `crop_strategy`: center, upper_third, lower_third, adaptive
- `normalize_brightness`: bool (per-channel histogram equalization)
- `background_mask_method`: none, green_threshold, saturation_threshold, dark_threshold
- `background_mask_threshold`: 0.1–0.8
- `min_brightness`, `max_brightness`: QC bounds (0–255 scale)
- `min_entropy`: 2.0–6.0 (reject low-information images)
- `percentile_trim`: 0.0–0.10 (trim extreme pixel values before averaging)

### Metric
Composite score = `R²(brightness ~ latitude)` − `0.5 × normalized_within_cell_variance`

- Higher R² = extraction captures real geographic signal
- Lower within-cell variance = extraction is robust to photo noise
- Variance normalized to 0–1 range (max ~2000) so both terms contribute equally

### Pipeline Sequence
1. **Local**: `run_pipeline.py` — pull 140K raw obs from iNat API, clean to 103K, assign H3 cells
2. **Local**: Generate photo manifest (103K URLs) + validation subset (1,000 obs) → upload to GCS
3. **GCP**: VM startup script clones repo, installs deps, downloads manifest from GCS
4. **GCP**: Download 103K photos (8 parallel workers, 0.5s rate limit per worker)
5. **GCP**: Run autoresearch loop (200 iterations, starting from locally-optimized config)
6. **GCP**: Final extraction with best config on ALL 103K photos
7. **GCP**: Upload results (experiments.jsonl, best_config.json, final_color_extract.csv) to GCS
8. **GCP**: VM self-stops (poweroff)
9. **Local**: Download results from GCS, run geographic analysis, generate publication figures

## GCP VM Specification

| Parameter | Value |
|-----------|-------|
| **VM Name** | `plethodon-full-pipeline` |
| **Project** | `us-con-gcp-sbx-0001526-030926` |
| **Zone** | `us-east1-b` |
| **Machine Type** | `n2-highmem-16` |
| | 16 vCPUs, 128 GB RAM |
| **Provisioning** | Spot (preemptible), auto-stop on termination |
| **Image** | `debian-12` (debian-cloud) |
| **Boot Disk** | 200 GB `pd-ssd` |
| **Network** | `dep-it-fhai01-ce-vpc` / `dep-it-fhai01-ce-vpc-sn-private-01` (private subnet, NAT for internet) |
| **External IP** | None (outbound via Cloud NAT) |
| **Service Account** | `dwm-pipeline-runner@us-con-gcp-sbx-0001526-030926.iam.gserviceaccount.com` |
| **Labels** | `project=plethodon-inat`, `study=study4-color`, `owner=kyoconnell`, `experiment=autoresearch-full` |
| **Deployment** | Self-contained startup script (`scripts/vm_startup.sh`), no SSH required |
| **Results Bucket** | `gs://dwm-wgs-incoming/plethodon/output/` |

### Why this VM size?
- **16 vCPUs**: Allows 8 parallel photo download workers + headroom for color extraction (PIL/numpy)
- **128 GB RAM**: Overkill for this workload (~4 GB actually needed), but n2-highmem was chosen for CPU count; n2-standard-16 (64 GB) would also work
- **200 GB SSD**: 103K photos × ~200 KB avg = ~20 GB, plus Python env, repo, intermediate files
- **Spot**: ~60–70% cheaper than on-demand; acceptable risk since the pipeline checkpoints progress and can resume

## Cost Estimates

### Spot VM pricing (n2-highmem-16, us-east1)
- **On-demand**: ~$1.05/hr
- **Spot**: ~$0.33/hr (68% discount)

### Pipeline phase breakdown

| Phase | Duration (est.) | Spot Cost (est.) | Notes |
|-------|----------------|-----------------|-------|
| **VM boot + setup** | ~5 min | $0.03 | apt-get, pip install, clone repo, download from GCS |
| **Photo download** | ~1.8 hr | $0.59 | 103K photos ÷ 8 workers × 0.5s rate limit |
| **Autoresearch loop** | ~5 hr | $1.65 | 200 iterations × ~90s each (1,000-photo validation set) |
| **Final extraction** | ~2.5 hr | $0.83 | 103K photos × extract_with_config (~90ms/photo) |
| **Upload + shutdown** | ~5 min | $0.03 | gsutil cp to GCS, poweroff |
| | | | |
| **Boot disk (200 GB SSD)** | ~10 hr | $0.34 | $0.204/GB/month = ~$0.034/hr for 200 GB |
| | | | |
| **Total estimated** | **~10 hr** | **~$3.47** | |

### Local compute costs
- **Data acquisition** (iNat API pull): ~35 min, no cloud cost
- **Test autoloop** (50 iterations on 859 photos): ~30 min, no cloud cost
- **Final analysis + figures**: ~5 min, no cloud cost

### Total project cloud spend: **~$3.50**

## Initial Test Results (Local, 859 photos, 50 iterations)

| Metric | Baseline | Optimized | Change |
|--------|----------|-----------|--------|
| Composite Score | −0.257 | +0.010 | +0.267 |
| R² (brightness ~ latitude) | 0.018 | 0.018 | stable |
| Within-cell variance | 1,101 | 33 | **−97%** |
| Photos passing QC | 859/859 | 859/859 | no loss |

### Optimized config (starting point for GCP run)
```json
{
  "central_crop_fraction": 0.641,
  "color_space": "lab",
  "crop_strategy": "center",
  "normalize_brightness": true,
  "background_mask_method": "none",
  "background_mask_threshold": 0.3,
  "min_brightness": 15,
  "max_brightness": 224,
  "min_entropy": 5.032,
  "percentile_trim": 0.047
}
```

### Key findings
1. **LAB color space** dramatically outperformed HSV and RGB — L* channel is perceptually uniform
2. **Histogram normalization** was the single biggest improvement — standardizes variable photo lighting
3. **Larger crop** (64% vs 40%) captured more dorsal surface
4. **Background masking was unhelpful** — central crop + normalization was sufficient
5. **Percentile trimming** (4.7%) provided marginal noise reduction

## Dataset Summary

| Metric | Value |
|--------|-------|
| Raw observations (iNat API) | 140,657 |
| After cleaning (obscured removal, dedup, type standardization) | 103,669 |
| Species | 34 |
| Year range | 1970–2026 |
| Top species: *P. cinereus* | 71,640 obs (69%) |
| H3 cells (resolution 5, ~252 km²) | 4,198 |
| Photos with valid URLs | 103,669 (100%) |
| Validation subset | 1,000 obs (26 species) |
