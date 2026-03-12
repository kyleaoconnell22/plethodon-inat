# Study 4: Geographic Variation in Dorsal Color in *Plethodon* — Context for Introduction

## The Study System

*Plethodon* is a genus of ~55 species of lungless salamanders (family Plethodontidae) endemic to North America. They are the most species-rich vertebrate genus in eastern North America, spanning from ~25°N to ~50°N latitude with a secondary radiation in the Pacific Northwest. Their ecology is remarkably well-studied: decades of work on competitive exclusion (Hairston 1951, Jaeger 1971), niche partitioning, and elevational zonation make them a model system in community ecology.

Two classic ecogeographic rules predict coloration patterns in this genus:

- **Gloger's rule**: Organisms in warmer, more humid environments tend to be more darkly pigmented. Predicts darker *Plethodon* at lower latitudes and in wetter habitats.
- **Thermal melanism hypothesis**: Darker coloration at higher elevations and latitudes helps ectotherms absorb solar radiation more efficiently. Predicts darker *Plethodon* at higher latitudes/elevations — the *opposite* direction from Gloger's rule.

These predictions yield opposite latitudinal gradients, making the direction of any observed cline immediately informative about which selective pressure dominates.

### Why iNaturalist?

iNaturalist (inaturalist.org) hosts >200 million observations of organisms worldwide, including ~154,000 Research Grade observations of *Plethodon*. This represents orders of magnitude more geographic coverage than any museum collection or field survey. The tradeoff is photo quality: observations are taken by citizen scientists with varying cameras, lighting, and photographic skill. Extracting reliable color measurements from these photos requires careful pipeline design — which is where the autoresearch approach enters.

### The Color Morph Validation Problem

*Plethodon cinereus* (the Eastern Red-backed Salamander) is the most commonly observed species (~80K observations). It exhibits two well-documented color morphs:
- **Redback**: A red/orange dorsal stripe
- **Leadback**: Uniformly dark dorsal coloration

Any color extraction pipeline that works correctly should, at minimum, be able to detect the brightness difference between these morphs. This serves as an internal validation.

## The Autoresearch Loop Approach

### Inspiration: Karpathy's autoresearch

In March 2026, Andrej Karpathy released [autoresearch](https://github.com/karpathy/autoresearch), a minimal Python framework (~630 lines) that turns ML experimentation into a tight automated loop: an AI agent proposes a change to a training script, runs a time-boxed experiment, measures whether loss improved, keeps or discards the change, and repeats. In one overnight run, the agent completed 126 experiments, systematically improving model performance without human intervention.

The core insight is simple: **any optimization problem with a clear, automatable evaluation metric can be driven by this loop.** The human writes the goal (in a `program.md` file), the agent handles the search.

### Application to Color Extraction

We adapted this pattern for ecological image analysis. The "training script" becomes the color extraction pipeline, and the "loss function" becomes a composite metric measuring geographic signal quality:

**Score = R²(brightness ~ latitude) - λ × mean(within-cell brightness variance)**

- **R²(brightness ~ latitude)**: Does the extracted brightness correlate with latitude? If real geographic clines exist (per Gloger's or thermal melanism), a good extraction pipeline should detect them.
- **Within-cell variance**: How noisy are brightness measurements within a single H3 hexagonal grid cell? Lower variance means the pipeline is robust to photo-quality differences.
- **λ = 0.5**: Balances signal detection vs. noise reduction.

The loop tunes extraction parameters — crop fraction, color space (HSV vs. LAB vs. RGB), histogram normalization, background masking, QC thresholds — one parameter at a time, keeping changes that improve the composite score.

## How We Got to This Study

### Original scope (3 studies)

The project was originally designed as three independent studies sharing a data pipeline:
1. **Study 2**: Effort-corrected range expansion analysis
2. **Study 3**: Species co-occurrence patterns (SIM9/C-score null models)
3. **Study 4**: Geographic variation in dorsal color

After building all three modules, we pivoted to focus exclusively on Study 4 because:
- It had the most novel methodological contribution (automated color extraction from citizen science photos)
- The autoresearch loop was a natural fit for optimizing the extraction pipeline
- The biological question (Gloger's vs. thermal melanism) yields a clear result regardless of direction

### Pipeline architecture

```
iNaturalist API (154K Research Grade Plethodon observations)
    │
    ▼
Data Cleaning (remove obscured coords, deduplicate, flag out-of-range)
    │
    ▼
H3 Grid Assignment (resolution 5, ~252 km² hexagonal cells)
    │
    ▼
Photo Download (~100K+ photos, rate-limited)
    │
    ▼
Autoresearch Loop (optimize extraction parameters)
    │
    ▼
Final Extraction (best config on all photos)
    │
    ▼
Geographic Analysis (OLS regression, mixed models, maps)
```

## The Initial Experiment

### Setup
- **Test dataset**: 859 cleaned observations (from first 10,000 API results), 24 species, years 1983–2018
- **859 photos** downloaded locally
- **Baseline config**: 40% central crop, HSV color space, no normalization, no masking
- **50 iterations** of the autoresearch loop

### Results

| Metric | Baseline | Optimized | Change |
|--------|----------|-----------|--------|
| Composite Score | -0.257 | +0.010 | +0.267 |
| R² (brightness ~ latitude) | 0.018 | 0.018 | stable |
| Within-cell variance | 1,101 | 33 | **-97%** |
| Photos passing QC | 859/859 | 859/859 | no loss |

### Key discoveries from the loop

The 12 accepted changes (out of 50 experiments, 24% acceptance rate) revealed:

1. **LAB color space** (CIE L\*a\*b\*) dramatically outperformed HSV and RGB. The L\* channel is perceptually uniform — equal numerical differences correspond to equal perceived brightness differences — making it a far better measure of dorsal lightness than HSV's V channel.

2. **Histogram normalization** was the single biggest improvement. By equalizing exposure per-channel before extraction, it standardizes the wildly variable lighting conditions across citizen science photos (flash vs. ambient, sun vs. shade, direct vs. reflected).

3. **Larger crop fraction** (64% vs. 40%) captured more dorsal surface area, reducing the influence of any single bright or dark pixel.

4. **Background masking was ultimately unhelpful** — the loop explored green-threshold, dark-threshold, and saturation-threshold masking, but eventually reverted to "none." The central crop + normalization approach was sufficient to exclude most background.

5. **Percentile trimming** (4.7% of extreme brightness values) provided marginal improvement by removing outlier pixels from the mean calculation.

The R² remained stable (~0.018) while within-cell variance dropped 97%, meaning the same geographic signal was detected with 33× less noise. This is the ideal outcome: the pipeline became much more precise without changing the signal it detected.

## What We Kicked Off

### Full-scale experiment

With the optimized config validated on the test set, we launched the full pipeline:

- **Full data pull**: All ~154,000 Research Grade *Plethodon* observations from iNaturalist API
- **Photo download**: ~100,000+ photos (on GCP spot VM, n2-highmem-16, rate-limited at 0.5s/photo)
- **Extended autoresearch loop**: 200 iterations starting from the test-optimized config, on a validation subset of the full dataset
- **Final extraction**: Best config applied to all downloaded photos
- **Results uploaded to GCS** for local analysis

The GCP VM runs autonomously via startup script — no SSH required. It clones the repo, installs dependencies, downloads photos, runs the loop, extracts colors, uploads results, and self-terminates.

### Code and reproducibility

All code is at: https://github.com/kyleaoconnell22/plethodon-inat

Key files:
- `src/study4_color/autoloop.py` — The autoresearch loop implementation
- `src/study4_color/program.md` — Optimization goals and parameter bounds
- `src/study4_color/analysis.py` — Geographic analysis and figure generation
- `scripts/launch_full_pipeline_vm.sh` — GCP deployment script
- `data/experiments/best_config.json` — Current best extraction config
- `data/experiments/experiments.jsonl` — Full experiment log

### Expected timeline

- API pull: ~30 minutes (770+ API pages at ~1 sec each)
- Photo download: ~14 hours (100K photos × 0.5 sec rate limit)
- Autoresearch loop: ~6 hours (200 iterations × ~90 sec each on full validation set)
- Final extraction: ~2 hours
- Total: ~24 hours of GCP compute (spot VM, ~$2-3 estimated cost)
