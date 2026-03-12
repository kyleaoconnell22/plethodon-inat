"""
Central configuration for the Plethodon iNaturalist research pipeline.
"""
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
CLEANED_DIR = DATA_DIR / "cleaned"
PHOTOS_DIR = DATA_DIR / "photos"
FIGURES_DIR = PROJECT_ROOT / "figures"

# ── iNaturalist API ────────────────────────────────────────────────────
INAT_TAXON_ID = 17684          # genus Plethodon on iNaturalist
INAT_PER_PAGE = 200            # max results per API page
INAT_RATE_LIMIT_DELAY = 1.0   # seconds between API calls
INAT_QUALITY_GRADE = "research"

# ── Spatial ────────────────────────────────────────────────────────────
H3_RES_BROAD = 5               # ~252 km² hexagons for broad patterns
H3_RES_FINE = 7                # ~5.2 km² hexagons for fine-scale
DUPLICATE_DISTANCE_M = 100     # meters — dedup threshold

# ── Temporal ───────────────────────────────────────────────────────────
YEAR_MIN = 2012                # pre-2012 iNat data too sparse
YEAR_MAX = 2026

# ── Study 3 ────────────────────────────────────────────────────────────
NULL_MODEL_ITERATIONS = 999
MIN_OBS_PER_CELL = 5           # effort threshold for co-occurrence

# Focus species pairs (common name, taxon IDs looked up at runtime)
FOCUS_PAIRS = [
    ("Plethodon cinereus", "Plethodon shenandoah"),
    ("Plethodon cinereus", "Plethodon nettingi"),
    ("Plethodon cinereus", "Plethodon virginia"),
    ("Plethodon cinereus", "Plethodon hubrichti"),
]

# ── Study 4 ────────────────────────────────────────────────────────────
PHOTO_DOWNLOAD_WORKERS = 4
PHOTO_RATE_LIMIT_DELAY = 1.0   # seconds between downloads
CENTRAL_CROP_FRACTION = 0.4    # fraction of image to keep (centered)
MIN_BRIGHTNESS = 15            # reject too-dark images (0-255 V channel)
MAX_BRIGHTNESS = 245           # reject overexposed images
MIN_IMAGE_ENTROPY = 4.0        # reject low-information images
