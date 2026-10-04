# Included inference models

AquaPulse includes the two ONNX exports used by the backend so a fresh clone can
run inference and build the application image. Other training runs, PyTorch
checkpoints, generated plots, and training images remain outside Git.

| Artifact | Purpose | Size in bytes |
|---|---|---:|
| `n_clean/weights/best.onnx` | YOLO11n breeding-container detection | 10,607,793 |
| `n_clean/eval/report.json` | Held-out detector results and validation-selected confidence threshold | 4,075 |
| `water_seg_s/weights/best.onnx` | YOLO11s-seg water segmentation inside detected containers | 40,557,112 |

The application runs these exports with ONNX Runtime's CPU execution provider.
The water model is used for container photos; it is not a general river-water or
pollution model. The detector uses the threshold recorded in `report.json`.

## Training provenance

These are AquaPulse fine-tunes of the pretrained `yolo11n.pt` and
`yolo11s-seg.pt` checkpoints from
[Ultralytics YOLO11](https://docs.ultralytics.com/models/yolo11/).
Both exports record Ultralytics **8.4.155** in their ONNX metadata, and were
exported on **2026-09-17 UTC** with batch size 1, static dimensions, and
simplification enabled. Input image size is 640 pixels.

The source dataset is **VisText-Mosquito, version 2**, Mendeley Data,
DOI [10.17632/rtsfh7jh7p.2](https://data.mendeley.com/datasets/rtsfh7jh7p/2),
published under **CC BY 4.0**. Preparation is implemented in
[`ml/prepare_vistext.py`](../prepare_vistext.py). The clean variant removes
stock-photo previews, deduplicates images, and assigns related scenes to the same
split using seed **42**. Image-level attribution is recorded in
[`data/sources.csv`](../../data/sources.csv); exclusion reasons are in
[`data/excluded.csv`](../../data/excluded.csv).

| Setting | Container detector | Water segmenter |
|---|---|---|
| Architecture | YOLO11n | YOLO11s-seg |
| Train / validation / test images | 1,132 / 341 / 167 | 89 / 33 / 19 |
| Dataset configuration | `data/data.yaml` | `data/water_seg/data.yaml` |
| Training seed | 0 | 0 |
| Maximum epochs | 50 | 200 |
| Completed epochs | 45 | 200 |
| Early-stopping patience | 15 | 50 |
| Batch size | 16 | 12 |
| Image size | 640 | 640 |

Training used the Linux CUDA environment in [`ml/Dockerfile`](../Dockerfile).
The detector orchestration and evaluation code are in
[`ml/train_all.sh`](../train_all.sh) and
[`ml/evaluate.py`](../evaluate.py). The small water-segmentation run was a separate
experiment; its recipe is included below because `train_all.sh` trains the nano
water variant instead.

## Recreating the serving models

Download and extract the source dataset into
`data/raw/vistext-mosquito/extracted`. Inside the training container, with the
repository mounted at `/workspace` and the working directory `/workspace/ml`,
run the following. The version pin matches the included exports.

```bash
pip install ultralytics==8.4.155
python prepare_vistext.py --seed 42

yolo detect train model=yolo11n.pt data=/workspace/data/data.yaml \
  epochs=50 patience=15 batch=16 imgsz=640 seed=0 workers=4 cache=ram \
  project=/workspace/ml/runs name=n_clean exist_ok=True plots=True
python evaluate.py --model runs/n_clean/weights/best.pt \
  --data /workspace/data/data.yaml

yolo segment train model=yolo11s-seg.pt data=/workspace/data/water_seg/data.yaml \
  epochs=200 patience=50 batch=12 imgsz=640 seed=0 workers=4 cache=ram \
  project=/workspace/ml/runs name=water_seg_s exist_ok=True plots=True

yolo export model=runs/n_clean/weights/best.pt format=onnx \
  imgsz=640 batch=1 dynamic=False simplify=True
yolo export model=runs/water_seg_s/weights/best.pt format=onnx \
  imgsz=640 batch=1 dynamic=False simplify=True
```

Hardware and library differences can change training results. These SHA-256
hashes identify the exact serving artifacts included in this repository:

```text
4b5db469eaa91c0f9fd4b2a0b3a500aa7a0228913c2533bdcc4c15a45498846a  n_clean/weights/best.onnx
f19e6c4c98a3f35feb613b43b9fbe9e0b1b684677a9b74176f226670040d9cff  water_seg_s/weights/best.onnx
```

## Model attribution and licenses

Both YOLO exports retain their upstream Ultralytics metadata, including
`AGPL-3.0 License (https://ultralytics.com/license)`. Upstream source is
[ultralytics/ultralytics](https://github.com/ultralytics/ultralytics);
the [upstream license](https://github.com/ultralytics/ultralytics/blob/main/LICENSE)
is the GNU Affero General Public License, version 3. The complete license from
the installed Ultralytics 8.4.155 distribution is preserved in
[`LICENSE.Ultralytics`](LICENSE.Ultralytics). The repository's training,
preprocessing, evaluation, and serving code describes the AquaPulse adaptations.
The dataset's CC BY 4.0 attribution remains separate from the model license.

The bundled face detector
[`face_detection_yunet_2023mar.onnx`](../../backend/models/face_detection_yunet_2023mar.onnx)
comes from the official
[OpenCV Zoo YuNet model directory](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet).
YuNet is copyright (c) 2020 Shiqi Yu and is distributed under the MIT License.
The upstream license text is preserved in
[`backend/models/LICENSE.YuNet`](../../backend/models/LICENSE.YuNet), from the
[official license file](https://github.com/opencv/opencv_zoo/blob/main/models/face_detection_yunet/LICENSE).
