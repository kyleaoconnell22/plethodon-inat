# Plethodon iNaturalist Research Pipeline

A reproducible data pipeline and analysis suite for studying the woodland salamander genus *Plethodon* using community science observations from [iNaturalist](https://www.inaturalist.org/).

## Studies

This project supports three independent analyses built on a shared data pipeline:

| Study | Topic | Description |
|-------|-------|-------------|
| **Study 2** | Range Expansion | Detects temporal shifts in species occurrence across H3 hexagonal grid cells to identify range expansion or contraction |
| **Study 3** | Co-occurrence | Tests for non-random spatial co-occurrence between focal *Plethodon* species pairs using null-model permutation tests |
| **Study 4** | Color Variation | Downloads observation photos, extracts color features, and analyzes geographic/temporal variation in dorsal color phenotypes |

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd plethodon-inat

# Create the conda environment
conda env create -f environment.yml
conda activate plethodon
```

### Requirements

- Python 3.12
- Key dependencies: pandas, geopandas, h3-py, scipy, scikit-image, opencv, pyinaturalist
- See `environment.yml` for the full list

## Usage

### 1. Run the shared data pipeline

Fetches all Research Grade *Plethodon* observations from the iNaturalist API, cleans and deduplicates them, and assigns H3 hexagonal grid cells.

```bash
# Full pipeline (fetch + clean + grid)
python run_pipeline.py

# Limit observations for a test run
python run_pipeline.py --max-obs 500

# Resume a previously interrupted fetch
python run_pipeline.py --resume

# Skip API fetch and re-clean/re-grid existing raw data
python run_pipeline.py --skip-acquire
```

### 2. Run Study 2 — Range Expansion

```bash
python run_study2.py

# Use a different H3 resolution (default: 5)
python run_study2.py --h3-res 7
```

### 3. Run Study 3 — Co-occurrence

```bash
python run_study3.py

# Use a different H3 resolution
python run_study3.py --h3-res 7
```

### 4. Run Study 4 — Color Variation

```bash
python run_study4.py

# Skip photo download if photos are already cached
python run_study4.py --skip-download

# Limit number of photos for testing
python run_study4.py --max-photos 100
```

## Project Structure

```
plethodon-inat/
├── run_pipeline.py          # Orchestrates shared data pipeline
├── run_study2.py            # Entry point for Study 2 (range expansion)
├── run_study3.py            # Entry point for Study 3 (co-occurrence)
├── run_study4.py            # Entry point for Study 4 (color variation)
├── environment.yml          # Conda environment specification
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── config.py            # Central configuration (paths, constants, parameters)
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── acquire.py       # iNaturalist API data acquisition
│   │   ├── clean.py         # Deduplication, filtering, QC flagging
│   │   └── grid.py          # H3 hexagonal grid assignment
│   ├── study2_range/
│   │   ├── __init__.py
│   │   └── analysis.py      # Range expansion analysis
│   ├── study3_cooccur/
│   │   ├── __init__.py
│   │   └── analysis.py      # Co-occurrence null model tests
│   └── study4_color/
│       ├── __init__.py
│       └── analysis.py      # Photo download, feature extraction, color analysis
│
├── data/
│   ├── raw/                 # Raw API output (parquet + CSV)
│   ├── cleaned/             # Cleaned and gridded datasets
│   └── photos/              # Downloaded observation photos (Study 4)
│
├── figures/                 # Generated plots and maps
└── docs/                    # Additional documentation
```

## Data Pipeline Architecture

```
iNaturalist API
      │
      ▼
┌─────────────┐
│   acquire    │  Paginated fetch, checkpoint/resume, rate limiting
└─────┬───────┘
      │  data/raw/plethodon_raw.parquet
      ▼
┌─────────────┐
│    clean     │  Remove obscured coords, dedup, QC flags, type standardization
└─────┬───────┘
      │  data/cleaned/plethodon_cleaned.parquet
      ▼
┌─────────────┐
│    grid      │  H3 cell assignment (res 5 + res 7), incidence matrices
└─────┬───────┘
      │  data/cleaned/plethodon_gridded.parquet
      │  data/cleaned/cells_res5.parquet
      │  data/cleaned/incidence_res5.parquet
      ▼
  Study 2 / Study 3 / Study 4
```

### Key design decisions

- **H3 hexagonal grid**: Uses Uber's H3 system for equal-area spatial binning, avoiding latitude-dependent distortion of rectangular grids.
- **Two resolutions**: Resolution 5 (~252 km^2) for broad biogeographic patterns; resolution 7 (~5.2 km^2) for fine-scale population analysis.
- **Checkpoint/resume**: API acquisition saves periodic checkpoints so interrupted fetches can be resumed without re-downloading.
- **Parquet storage**: All intermediate datasets are saved as Parquet for efficient I/O and type preservation, with CSV copies of key files for human inspection.

## Dependencies

| Package | Purpose |
|---------|---------|
| pyinaturalist | iNaturalist API client |
| pandas | Tabular data processing |
| geopandas | Spatial data handling |
| h3-py | Hexagonal grid system |
| scipy | Statistical tests |
| scikit-image | Image feature extraction (Study 4) |
| opencv | Image processing (Study 4) |
| matplotlib / seaborn | Visualization |
| statsmodels | Statistical modeling |

## Citation

If you use this pipeline or its outputs, please cite:

> [Author(s)]. *Plethodon iNaturalist Research Pipeline*. [Year]. [URL].

Data sourced from iNaturalist (https://www.inaturalist.org/). Please also cite iNaturalist per their [citation guidelines](https://www.inaturalist.org/pages/cite).

## License

[License placeholder]
