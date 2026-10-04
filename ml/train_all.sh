#!/usr/bin/env bash
# Train and evaluate the AquaPulse detectors inside the aquapulse-ml container:
#   docker run -d --name aquapulse-train --gpus all --shm-size=4g \
#     -v "<repo>:/workspace" aquapulse-ml bash /workspace/ml/train_all.sh
# Follow progress with: docker logs -f aquapulse-train
set -euo pipefail
cd /workspace/ml

CLEAN=/workspace/data/data.yaml
STOCK=/workspace/data/variants/with_stock/data.yaml
COMMON="epochs=50 imgsz=640 patience=15 seed=0 workers=4 cache=ram project=/workspace/ml/runs exist_ok=True plots=True"

# Both steps skip work that already finished, so the script can be re-run after a failure.
train() {  # name model data batch
  if [[ -f "runs/$1/.done" ]]; then
    echo "===== skip train $1 (already finished)"; return
  fi
  echo "===== train $1 ($2, batch $4) $(date -Is)"
  yolo detect train model="$2" data="$3" batch="$4" name="$1" $COMMON
  touch "runs/$1/.done"
}

evaluate() {  # name data [extra args]
  local name=$1 data=$2; shift 2
  local suffix=""
  [[ $# -gt 0 ]] && suffix="_no_${*: -1}"
  if [[ -f "runs/$name/eval$suffix/report.json" ]]; then
    echo "===== skip evaluate $name $* (report exists)"; return
  fi
  echo "===== evaluate $name $* $(date -Is)"
  python evaluate.py --model "runs/$name/weights/best.pt" --data "$data" "$@"
}

train n_clean yolo11n.pt "$CLEAN" 16
evaluate n_clean "$CLEAN"

train s_clean yolo11s.pt "$CLEAN" 12
evaluate s_clean "$CLEAN"

train s_stock yolo11s.pt "$STOCK" 12
evaluate s_stock "$STOCK"
evaluate s_stock "$STOCK" --exclude-origin stock_photo_preview

# Water surface segmentation: only 89 training images, so more epochs and more patience.
WATER=/workspace/data/water_seg/data.yaml
if [[ -f runs/water_seg/.done ]]; then
  echo "===== skip train water_seg (already finished)"
else
  echo "===== train water_seg (yolo11n-seg.pt) $(date -Is)"
  yolo segment train model=yolo11n-seg.pt data="$WATER" batch=16 name=water_seg     epochs=100 imgsz=640 patience=25 seed=0 workers=4 cache=ram     project=/workspace/ml/runs exist_ok=True plots=True
  touch runs/water_seg/.done
fi
echo "===== evaluate water_seg (mask metrics on test) $(date -Is)"
yolo segment val model=runs/water_seg/weights/best.pt data="$WATER" split=test imgsz=640   project=/workspace/ml/runs/water_seg name=eval_test exist_ok=True plots=True

echo "===== all done $(date -Is)"
