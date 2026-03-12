# Study 4: Dorsal Color Variation with Autoresearch Loop

**Date**: 2026-03-12
**Status**: Approved

## Goal
Determine whether dorsal lightness/darkness in *Plethodon* varies predictably with latitude, elevation, or climate (Gloger's rule vs. thermal melanism hypothesis) using iNaturalist photos and an automated parameter optimization loop.

## Architecture

### Compute
- **Local**: Data acquisition, cleaning, grid assignment, photo manifest generation, final analysis + figures
- **GCP VM** (us-west1-b, spot, n2-highmem-16): Photo download, color extraction, autoresearch loop
- **Labels**: `project=plethodon-inat,study=study4-color,owner=kyoconnell,experiment=autoresearch`

### Autoresearch Loop (runs on GCP VM)
1. `program.md` defines high-level optimization goal
2. LLM proposes changes to `extract_config` (a Python dict, not arbitrary code)
3. Run extraction on validation subset (500-1000 photos)
4. Measure composite score: `R²(brightness ~ latitude) - λ * mean(within_cell_variance)`
5. If score > best: keep config. Else: revert.
6. Log experiment to `experiments/` directory
7. Repeat for N iterations

### What the loop tunes
- `central_crop_fraction`: 0.2 - 0.6
- `color_space`: HSV, LAB, RGB
- `crop_strategy`: center, upper_third, adaptive
- `normalize_brightness`: bool (histogram equalization before extraction)
- `background_mask`: none, green_threshold, saturation_threshold
- `min_brightness`, `max_brightness`, `min_entropy`: QC thresholds

### Metric
Composite score = `R²(brightness ~ latitude)` penalized by `mean(within_cell_brightness_variance)`.
- Higher R² = extraction captures real geographic signal
- Lower within-cell variance = less photo noise
- Lambda (penalty weight) tunable, default 0.5

### Pipeline Sequence
1. Local: `run_pipeline.py` → cleaned + gridded data
2. Local: Generate photo manifest
3. SCP manifest + code to GCP VM
4. GCP: Download photos (parallel, rate-limited)
5. GCP: Run autoresearch loop (unattended, overnight)
6. GCP: Final extraction with best params on ALL photos
7. SCP results CSV back to local
8. Local: Geographic analysis, mixed models, publication figures

## GCP VM Spec
- Zone: us-west1-b
- Machine: n2-highmem-16 (spot)
- Image: common-cpu-debian-11-py310 (deeplearning-platform-release)
- Boot disk: 50GB pd-ssd
- Scratch disk: 100GB pd-ssd (photos)
- Service account: dwm-pipeline-runner@us-con-gcp-sbx-0001526-030926.iam.gserviceaccount.com
- Labels: project=plethodon-inat, study=study4-color, owner=kyoconnell, experiment=autoresearch
