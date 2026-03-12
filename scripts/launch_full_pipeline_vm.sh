#!/usr/bin/env bash
set -euo pipefail

PROJECT="us-con-gcp-sbx-0001526-030926"
ZONE="us-east1-b"
VM_NAME="plethodon-full-pipeline"
SA="dwm-pipeline-runner@${PROJECT}.iam.gserviceaccount.com"
NETWORK="dep-it-fhai01-ce-vpc"
SUBNET="dep-it-fhai01-ce-vpc-sn-private-01"
GCS_BUCKET="gs://dwm-wgs-incoming/plethodon"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOCAL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 1. Upload data to GCS
echo "=== Uploading data to GCS ==="
gsutil -m cp \
    "$LOCAL_DIR/data/photos/photo_manifest.csv" \
    "$LOCAL_DIR/data/cleaned/validation_subset.csv" \
    "$LOCAL_DIR/data/experiments/best_config.json" \
    "${GCS_BUCKET}/input/"
echo "   Done."

# 2. Create VM with startup script from file
echo "=== Creating VM ==="
gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT" \
    --zone="$ZONE" \
    --machine-type=n2-highmem-32 \
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
    --labels=project=plethodon-inat,study=study4-color,owner=kyoconnell,experiment=autoresearch-full,provisioning=ondemand \
    --metadata-from-file=startup-script="$SCRIPT_DIR/vm_startup.sh"

echo ""
echo "============================================================"
echo "  VM launched: $VM_NAME"
echo "  Zone: $ZONE"
echo "============================================================"
echo ""
echo "Monitor via serial port:"
echo "  gcloud compute instances get-serial-port-output $VM_NAME --zone=$ZONE --project=$PROJECT 2>&1 | tail -30"
echo ""
echo "Check GCS for results:"
echo "  gsutil ls ${GCS_BUCKET}/output/"
echo ""
echo "Retrieve results:"
echo "  mkdir -p data/experiments/gcp_results"
echo "  gsutil -m cp -r ${GCS_BUCKET}/output/ data/experiments/gcp_results/"
echo ""
echo "Delete VM when done:"
echo "  gcloud compute instances delete $VM_NAME --zone=$ZONE --project=$PROJECT --quiet"
echo ""
