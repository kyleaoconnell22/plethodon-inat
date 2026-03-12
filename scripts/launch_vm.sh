#!/usr/bin/env bash
set -euo pipefail

PROJECT="us-con-gcp-sbx-0001526-030926"
ZONE="us-east1-b"
VM_NAME="plethodon-color-vm"
SA="dwm-pipeline-runner@${PROJECT}.iam.gserviceaccount.com"
NETWORK="dep-it-fhai01-ce-vpc"
SUBNET="dep-it-fhai01-ce-vpc-sn-private-01"

gcloud compute instances create "$VM_NAME" \
    --project="$PROJECT" \
    --zone="$ZONE" \
    --machine-type=n2-highmem-16 \
    --provisioning-model=SPOT \
    --instance-termination-action=STOP \
    --image-family=debian-12 \
    --image-project=debian-cloud \
    --boot-disk-size=100GB \
    --boot-disk-type=pd-ssd \
    --no-address \
    --network="$NETWORK" \
    --subnet="$SUBNET" \
    --scopes=cloud-platform \
    --service-account="$SA" \
    --account=kyoconnell@ocg.deloitte.com \
    --labels=project=plethodon-inat,study=study4-color,owner=kyoconnell,experiment=autoresearch \
    --metadata="startup-script=#! /bin/bash
apt-get update && apt-get install -y python3-pip python3-venv git tmux
mkdir -p /opt/plethodon
chmod 777 /opt/plethodon
"

echo ""
echo "VM created: $VM_NAME (zone=$ZONE, network=$NETWORK/$SUBNET)"
echo "SSH: gcloud compute ssh $VM_NAME --zone=$ZONE --project=$PROJECT"
