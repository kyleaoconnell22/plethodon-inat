#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# launch_full_pipeline_vm.sh
#
# Creates a self-contained GCP spot VM that:
#   1. Clones the repo
#   2. Installs Python dependencies
#   3. Downloads photo manifest + validation CSV from GCS
#   4. Downloads all photos (rate-limited)
#   5. Runs autoresearch loop (200 iterations)
#   6. Runs final extraction with best config on ALL photos
#   7. Uploads results to GCS
#   8. Self-terminates
#
# No SSH needed — monitor via serial port logs or GCS output.
# ---------------------------------------------------------------

PROJECT="us-con-gcp-sbx-0001526-030926"
ZONE="us-east1-b"
VM_NAME="plethodon-full-pipeline"
SA="dwm-pipeline-runner@${PROJECT}.iam.gserviceaccount.com"
NETWORK="dep-it-fhai01-ce-vpc"
SUBNET="dep-it-fhai01-ce-vpc-sn-private-01"
GCS_BUCKET="gs://dwm-wgs-incoming/plethodon"

# Upload local data files to GCS first
echo "=== Uploading data to GCS ==="
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

gsutil -m cp \
    "$LOCAL_DIR/data/photos/photo_manifest.csv" \
    "$LOCAL_DIR/data/cleaned/validation_subset.csv" \
    "$LOCAL_DIR/data/experiments/best_config.json" \
    "${GCS_BUCKET}/input/"

echo "   Uploaded manifest, validation subset, and best config to ${GCS_BUCKET}/input/"

# Create the VM with a comprehensive startup script
gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT" \
    --zone="$ZONE" \
    --machine-type=n2-highmem-16 \
    --provisioning-model=SPOT \
    --instance-termination-action=STOP \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=200GB \
    --boot-disk-type=pd-ssd \
    --no-address \
    --network="$NETWORK" \
    --subnet="$SUBNET" \
    --scopes=cloud-platform \
    --service-account="$SA" \
    --account=kyoconnell@ocg.deloitte.com \
    --labels=project=plethodon-inat,study=study4-color,owner=kyoconnell,experiment=autoresearch-full \
    --metadata=startup-script='#!/bin/bash
set -euxo pipefail

WORK=/opt/plethodon
GCS="gs://dwm-wgs-incoming/plethodon"
LOG="$WORK/pipeline.log"

exec > >(tee -a "$LOG") 2>&1
echo "=== $(date) Starting Plethodon full pipeline ==="

# 1. Install system deps
apt-get update -qq
apt-get install -y -qq python3-pip python3-venv git

# 2. Set up workspace
mkdir -p "$WORK"
cd "$WORK"

# 3. Clone repo
if [ ! -d plethodon-inat ]; then
    git clone https://github.com/kyleaoconnell22/plethodon-inat.git
fi
cd plethodon-inat

# 4. Create Python venv and install deps
python3 -m venv .venv
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet \
    pandas numpy pyarrow h3 scipy matplotlib seaborn \
    scikit-image opencv-python-headless statsmodels \
    pillow requests tqdm pyinaturalist

# 5. Download input files from GCS
mkdir -p data/photos data/cleaned data/experiments
gsutil cp "$GCS/input/photo_manifest.csv" data/photos/
gsutil cp "$GCS/input/validation_subset.csv" data/cleaned/
gsutil cp "$GCS/input/best_config.json" data/experiments/

echo "=== $(date) Downloading photos ==="

# 6. Download photos
python3 -c "
import sys; sys.path.insert(0, \".\")
import pandas as pd
from src.study4_color.analysis import download_photos
manifest = pd.read_csv(\"data/photos/photo_manifest.csv\")
print(f\"Downloading {len(manifest)} photos...\")
download_photos(manifest, output_dir=\"data/photos\", max_workers=8, rate_limit=0.5)
"

echo "=== $(date) Running autoresearch loop ==="

# 7. Run autoresearch loop (200 iterations, starting from best config)
python3 -c "
import sys, json; sys.path.insert(0, \".\")
import pandas as pd
from src.study4_color.autoloop import run_loop

val_df = pd.read_csv(\"data/cleaned/validation_subset.csv\")
with open(\"data/experiments/best_config.json\") as f:
    initial_config = json.load(f)

print(f\"Starting autoloop with {len(val_df)} validation obs\")
print(f\"Initial config: {json.dumps(initial_config, indent=2)}\")

best_config, best_score = run_loop(
    photo_dir=\"data/photos\",
    validation_df=val_df,
    n_iterations=200,
    exp_dir=\"data/experiments\",
    initial_config=initial_config,
    seed=123,
)
print(f\"Best score: {best_score}\")
"

echo "=== $(date) Running final extraction ==="

# 8. Run final extraction with best config on ALL photos
python3 -c "
import sys, json; sys.path.insert(0, \".\")
import pandas as pd
from src.study4_color.autoloop import extract_with_config, DEFAULT_CONFIG
from pathlib import Path
from tqdm import tqdm

with open(\"data/experiments/best_config.json\") as f:
    config = json.load(f)

manifest = pd.read_csv(\"data/photos/photo_manifest.csv\")
val_df = pd.read_csv(\"data/cleaned/validation_subset.csv\")

results = []
photo_dir = Path(\"data/photos\")
for row in tqdm(manifest.itertuples(), total=len(manifest), desc=\"Final extraction\"):
    fpath = photo_dir / f\"{row.obs_id}.jpg\"
    if not fpath.exists():
        continue
    extracted = extract_with_config(fpath, config)
    if extracted is not None:
        results.append({
            \"obs_id\": row.obs_id,
            \"mean_brightness\": extracted[\"brightness\"],
            \"entropy\": extracted[\"entropy\"],
        })

color_df = pd.DataFrame(results)
color_df.to_csv(\"data/experiments/final_color_extract.csv\", index=False)
print(f\"Final extraction: {len(color_df)} photos processed\")
"

echo "=== $(date) Uploading results to GCS ==="

# 9. Upload results
gsutil -m cp \
    data/experiments/experiments.jsonl \
    data/experiments/best_config.json \
    data/experiments/final_color_extract.csv \
    "$GCS/output/"

# Also upload the full log
gsutil cp "$LOG" "$GCS/output/pipeline.log"

echo "=== $(date) Pipeline complete! ==="
echo "Results at: $GCS/output/"

# 10. Self-terminate (stop, not delete — preserves disk for debugging)
echo "Self-stopping VM in 60 seconds..."
sleep 60
poweroff
'

echo ""
echo "============================================================"
echo "  VM launched: $VM_NAME"
echo "  Zone: $ZONE"
echo "  Labels: project=plethodon-inat, experiment=autoresearch-full"
echo "============================================================"
echo ""
echo "Monitor progress:"
echo "  Serial port: gcloud compute instances get-serial-port-output $VM_NAME --zone=$ZONE --project=$PROJECT"
echo "  GCS output:  gsutil ls ${GCS_BUCKET}/output/"
echo ""
echo "When done, retrieve results:"
echo "  gsutil -m cp -r ${GCS_BUCKET}/output/ ./data/experiments/gcp_results/"
echo ""
echo "Delete VM when finished:"
echo "  gcloud compute instances delete $VM_NAME --zone=$ZONE --project=$PROJECT --quiet"
echo ""
