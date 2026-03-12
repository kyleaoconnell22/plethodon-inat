# Autoresearch: Plethodon Dorsal Color Extraction Optimization

## Goal
Optimize the photo color extraction pipeline to maximize geographic signal
in dorsal brightness measurements across Plethodon salamander observations.

## Metric
Composite score = R²(mean_brightness ~ latitude) - 0.5 * mean(within_cell_brightness_variance)

- Higher R² means the extraction captures real latitudinal clines in coloration
- Lower within-cell variance means the extraction is robust to photo noise
- Lambda = 0.5 balances signal detection vs. noise reduction

## What you can change
Edit the `extract_config` dictionary in the experiment. Tunable parameters:

- `central_crop_fraction`: float 0.15-0.7 (fraction of image to keep, centered)
- `color_space`: "hsv", "lab", or "rgb" (which space to measure brightness in)
- `crop_strategy`: "center", "upper_third", "lower_third", "adaptive"
- `normalize_brightness`: bool (apply histogram equalization before extraction)
- `background_mask_method`: "none", "green_threshold", "saturation_threshold", "dark_threshold"
- `background_mask_threshold`: float 0.0-1.0 (threshold for masking)
- `min_brightness`: int 0-50 (QC: reject too-dark images)
- `max_brightness`: int 200-255 (QC: reject overexposed images)
- `min_entropy`: float 2.0-6.0 (QC: reject low-information images)
- `percentile_trim`: float 0.0-0.1 (trim extreme brightness values before averaging)

## Constraints
- Change ONE parameter per experiment (isolate effects)
- Each experiment runs on the same validation subset (500-1000 photos)
- Log every experiment with full config, score, and delta from previous best
- Never change the evaluation metric or validation set within a run

## Biology context
Plethodon salamanders span ~25-50°N latitude in eastern North America.
If dorsal coloration follows Gloger's rule (darker in warm/humid) or
thermal melanism (darker at high elevation/latitude), a good extraction
pipeline should detect a significant brightness ~ latitude relationship.
The signal may be weak (R² ~ 0.01-0.10) given photo noise, so every
improvement in extraction quality matters.
