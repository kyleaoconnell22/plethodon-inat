#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# deploy_and_run.sh — Run LOCALLY to push data to the VM and
# kick off photo download + autoresearch loop in tmux.
# ---------------------------------------------------------------

PROJECT="us-con-gcp-sbx-0001526-030926"
ZONE="us-west1-b"
VM_NAME="plethodon-color-vm"
REMOTE_DIR="/opt/plethodon/plethodon-inat"
LOCAL_PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SSH="gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT"
SCP="gcloud compute scp --zone=$ZONE --project=$PROJECT"

# ── 1. Upload data files ────────────────────────────────────────
echo "=== 1. Uploading data files to VM ==="

# Photo manifest
MANIFEST="$LOCAL_PROJECT_DIR/data/photos/photo_manifest.csv"
if [ ! -f "$MANIFEST" ]; then
    echo "ERROR: photo_manifest.csv not found. Run the pipeline locally first."
    exit 1
fi

# Validation subset (gridded data for the autoloop)
VALIDATION="$LOCAL_PROJECT_DIR/data/cleaned/validation_subset.csv"
GRIDDED="$LOCAL_PROJECT_DIR/data/cleaned/plethodon_gridded.parquet"

$SCP "$MANIFEST" "$VM_NAME:$REMOTE_DIR/data/photos/photo_manifest.csv"
echo "   Uploaded photo_manifest.csv"

if [ -f "$VALIDATION" ]; then
    $SCP "$VALIDATION" "$VM_NAME:$REMOTE_DIR/data/cleaned/validation_subset.csv"
    echo "   Uploaded validation_subset.csv"
fi

if [ -f "$GRIDDED" ]; then
    $SCP "$GRIDDED" "$VM_NAME:$REMOTE_DIR/data/cleaned/plethodon_gridded.parquet"
    echo "   Uploaded plethodon_gridded.parquet"
fi

# ── 2. Download photos in tmux ──────────────────────────────────
echo "=== 2. Starting photo download + autoresearch loop ==="

$SSH --command="tmux new-session -d -s study4 '\
    source /opt/conda/etc/profile.d/conda.sh && \
    conda activate plethodon && \
    cd $REMOTE_DIR && \
    echo \"=== Phase 1: Downloading photos ===\" && \
    python -c \"
import sys; sys.path.insert(0, \\\".\\\")
import pandas as pd
from src.study4_color.analysis import download_photos
manifest = pd.read_csv(\\\"data/photos/photo_manifest.csv\\\")
download_photos(manifest, output_dir=\\\"data/photos\\\")
\" 2>&1 | tee photo_download.log && \
    echo \"=== Phase 2: Running autoresearch loop ===\" && \
    python run_autoloop.py \
        --photo-dir data/photos \
        --validation-csv data/cleaned/validation_subset.csv \
        --n-iterations 200 \
        --exp-dir data/experiments \
    2>&1 | tee autoloop.log; \
    echo \"=== All done ===\"; \
    bash'"

echo ""
echo "============================================"
echo "  Pipeline launched in tmux session 'study4'"
echo "============================================"
echo ""
echo "To attach:"
echo "  $SSH -- tmux attach -t study4"
echo ""
echo "To check photo download progress:"
echo "  $SSH -- tail -f $REMOTE_DIR/photo_download.log"
echo ""
echo "To check autoloop progress:"
echo "  $SSH -- tail -f $REMOTE_DIR/autoloop.log"
echo ""
echo "To retrieve results when done:"
echo "  $SCP $VM_NAME:$REMOTE_DIR/data/experiments/best_config.json ./data/experiments/"
echo "  $SCP $VM_NAME:$REMOTE_DIR/data/experiments/experiments.jsonl ./data/experiments/"
echo ""
