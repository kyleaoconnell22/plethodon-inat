#!/usr/bin/env bash
set -euo pipefail

PROJECT="us-con-gcp-sbx-0001526-030926"
ZONE="us-west1-b"
VM_NAME="plethodon-color-vm"
SA="dwm-pipeline-runner@${PROJECT}.iam.gserviceaccount.com"

gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT" \
    --zone="$ZONE" \
    --machine-type=n2-highmem-16 \
    --provisioning-model=SPOT \
    --instance-termination-action=STOP \
    --image-family=common-cpu-debian-11-py310 \
    --image-project=deeplearning-platform-release \
    --boot-disk-size=50GB \
    --boot-disk-type=pd-ssd \
    --scopes=cloud-platform \
    --service-account="$SA" \
    --account=kyoconnell@ocg.deloitte.com \
    --labels=project=plethodon-inat,study=study4-color,owner=kyoconnell,experiment=autoresearch \
    --metadata="startup-script=#! /bin/bash
# Format and mount scratch space on boot disk (no separate scratch disk needed for this)
mkdir -p /opt/plethodon
chmod 777 /opt/plethodon
"

echo "VM created: $VM_NAME"
echo "SSH: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT"
