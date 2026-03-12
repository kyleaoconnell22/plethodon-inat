#!/bin/bash
set -euxo pipefail

WORK=/opt/plethodon
GCS="gs://dwm-wgs-incoming/plethodon"
LOG="$WORK/pipeline.log"

mkdir -p "$WORK"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date) Starting Plethodon full pipeline ==="

# 1. Install system deps
apt-get update -qq
apt-get install -y -qq python3-pip python3-venv git

# 2. Clone repo
cd "$WORK"
if [ ! -d plethodon-inat ]; then
    git clone https://github.com/kyleaoconnell22/plethodon-inat.git
fi
cd plethodon-inat

# 3. Create Python venv and install deps
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet \
    pandas numpy pyarrow h3 scipy matplotlib seaborn \
    scikit-image opencv-python-headless statsmodels \
    pillow requests tqdm pyinaturalist

# 4. Download input files from GCS
mkdir -p data/photos data/cleaned data/experiments
gsutil cp "$GCS/input/photo_manifest.csv" data/photos/
gsutil cp "$GCS/input/validation_subset.csv" data/cleaned/
gsutil cp "$GCS/input/best_config.json" data/experiments/

MANIFEST_COUNT=$(wc -l < data/photos/photo_manifest.csv)
echo "=== $(date) Downloading $MANIFEST_COUNT photos ==="

# 5. Download photos
python3 << 'PYEOF'
import sys; sys.path.insert(0, ".")
import pandas as pd
from src.study4_color.analysis import download_photos
manifest = pd.read_csv("data/photos/photo_manifest.csv")
print(f"Downloading {len(manifest)} photos...")
download_photos(manifest, output_dir="data/photos", max_workers=16, rate_limit=0.5)
PYEOF

echo "=== $(date) Running autoresearch loop (200 iterations) ==="

# 6. Run autoresearch loop
python3 << 'PYEOF'
import sys, json; sys.path.insert(0, ".")
import pandas as pd
from src.study4_color.autoloop import run_loop

val_df = pd.read_csv("data/cleaned/validation_subset.csv")
with open("data/experiments/best_config.json") as f:
    initial_config = json.load(f)

print(f"Starting autoloop with {len(val_df)} validation obs")
best_config, best_score = run_loop(
    photo_dir="data/photos",
    validation_df=val_df,
    n_iterations=200,
    exp_dir="data/experiments",
    initial_config=initial_config,
    seed=123,
)
print(f"Best score: {best_score}")
PYEOF

echo "=== $(date) Running final extraction with best config ==="

# 7. Final extraction on ALL photos
python3 << 'PYEOF'
import sys, json; sys.path.insert(0, ".")
import pandas as pd
from src.study4_color.autoloop import extract_with_config
from pathlib import Path
from tqdm import tqdm

with open("data/experiments/best_config.json") as f:
    config = json.load(f)

manifest = pd.read_csv("data/photos/photo_manifest.csv")
results = []
photo_dir = Path("data/photos")
for row in tqdm(manifest.itertuples(), total=len(manifest), desc="Final extraction"):
    fpath = photo_dir / f"{row.obs_id}.jpg"
    if not fpath.exists():
        continue
    extracted = extract_with_config(fpath, config)
    if extracted is not None:
        results.append({
            "obs_id": row.obs_id,
            "mean_brightness": extracted["brightness"],
            "entropy": extracted["entropy"],
        })

color_df = pd.DataFrame(results)
color_df.to_csv("data/experiments/final_color_extract.csv", index=False)
print(f"Final extraction: {len(color_df)} photos processed")
PYEOF

echo "=== $(date) Uploading results to GCS ==="

# 8. Upload results
gsutil -m cp \
    data/experiments/experiments.jsonl \
    data/experiments/best_config.json \
    data/experiments/final_color_extract.csv \
    "$GCS/output/"

gsutil cp "$LOG" "$GCS/output/pipeline.log"

echo "=== $(date) Pipeline complete! Results at: $GCS/output/ ==="

# 9. Self-stop
sleep 60
poweroff
