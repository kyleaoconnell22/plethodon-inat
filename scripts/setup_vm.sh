#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------
# setup_vm.sh — Run ON the GCP VM after SSH-ing in.
# Clones the repo, creates the Python env, and sets up data dirs.
# ---------------------------------------------------------------

REPO_URL="https://github.com/kyleaoconnell22/plethodon-inat.git"
WORK_DIR="/opt/plethodon"
ENV_NAME="plethodon"
CONDA="/opt/conda/bin/conda"

echo "=== 1. Cloning repo ==="
cd "$WORK_DIR"
if [ -d "plethodon-inat" ]; then
    echo "Repo already cloned — pulling latest..."
    cd plethodon-inat && git pull && cd ..
else
    git clone "$REPO_URL"
fi

echo "=== 2. Creating conda environment ==="
$CONDA create -y -n "$ENV_NAME" python=3.10
eval "$($CONDA shell.bash hook)"
conda activate "$ENV_NAME"

pip install --upgrade pip
pip install \
    pandas \
    numpy \
    h3 \
    scipy \
    matplotlib \
    seaborn \
    scikit-image \
    opencv-python \
    statsmodels \
    pillow \
    requests \
    tqdm \
    pyinaturalist

echo "=== 3. Creating data directories ==="
mkdir -p "$WORK_DIR/plethodon-inat/data/photos"
mkdir -p "$WORK_DIR/plethodon-inat/data/cleaned"
mkdir -p "$WORK_DIR/plethodon-inat/data/raw"
mkdir -p "$WORK_DIR/plethodon-inat/figures"

echo ""
echo "============================================"
echo "  Setup complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Activate the env:  conda activate $ENV_NAME"
echo "  2. cd $WORK_DIR/plethodon-inat"
echo "  3. Copy photo_manifest.csv into data/cleaned/ or data/photos/"
echo "  4. Run the Study 4 pipeline:  python run_study4.py"
echo ""
