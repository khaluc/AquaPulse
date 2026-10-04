"""Evaluate an AquaPulse YOLO detector the way the alerting system will use it.

1. Choose one confidence threshold on the *val* split: the highest threshold whose
   box recall still reaches --target-recall (missing a breeding site costs more
   than a false alarm that a human reviewer will dismiss).
2. Report on the *test* split at that threshold:
   - box precision / recall / F1 per class (IoU >= 0.5, class must match)
   - image-level recall: images with any labelled object where the model fires at all
   - calibration: reliability table, ECE and a reliability diagram
   - Ultralytics mAP50 / mAP50-95 per class and its confusion matrix

Usage:
  python ml/evaluate.py --model ml/runs/NAME/weights/best.pt --data data/data.yaml
         [--target-recall 0.8] [--exclude-origin stock_photo_preview]

--exclude-origin drops test/val images whose origin in the dataset's sources.csv
matches, e.g. to score a model on real phone photos only.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

IOU_THRESHOLD = 0.5
CONF_FLOOR = 0.01
THRESHOLD_GRID = [round(0.05 * i, 2) for i in range(1, 20)]  # 0.05 .. 0.95
CALIBRATION_BINS = 10
PREDICT_BATCH = 16


@dataclass
class Prediction:
    cls: int
    conf: float
    box: tuple[float, float, float, float]  # normalized xyxy
    matched: bool = False


@dataclass
class ImageResult:
    name: str
    gt: list[tuple[int, tuple[float, float, float, float]]]
    preds: list[Prediction]


def iou(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def match_image(image: ImageResult, iou_threshold: float = IOU_THRESHOLD) -> None:
    """Greedy matching by descending confidence, one ground truth per prediction.

    Because higher-confidence predictions claim ground truth first, a prediction's
    matched flag does not change when lower-confidence predictions are cut, so the
    flags computed once at CONF_FLOOR hold for every threshold.
    """
    taken = [False] * len(image.gt)
    for pred in sorted(image.preds, key=lambda p: -p.conf):
        best, best_iou = -1, iou_threshold
        for i, (gt_cls, gt_box) in enumerate(image.gt):
            if taken[i] or gt_cls != pred.cls:
                continue
            overlap = iou(pred.box, gt_box)
            if overlap >= best_iou:
                best, best_iou = i, overlap
        pred.matched = best >= 0
        if best >= 0:
            taken[best] = True


def counts_at(images: list[ImageResult], threshold: float, cls: int | None = None) -> dict[str, int]:
    tp = fp = gt = 0
    for image in images:
        gt += sum(1 for c, _ in image.gt if cls is None or c == cls)
        for pred in image.preds:
            if pred.conf < threshold or (cls is not None and pred.cls != cls):
                continue
            if pred.matched:
                tp += 1
            else:
                fp += 1
    return {"tp": tp, "fp": fp, "fn": gt - tp, "gt": gt}


def prf(counts: dict[str, int]) -> dict[str, float | None]:
    tp, fp, gt = counts["tp"], counts["fp"], counts["gt"]
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / gt if gt else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def choose_threshold(images: list[ImageResult], target_recall: float) -> tuple[float, bool]:
    """Highest grid threshold whose overall box recall reaches the target.

    Returns (threshold, reached). If no threshold reaches it, the lowest one is used.
    """
    reaching = [
        t for t in THRESHOLD_GRID if (prf(counts_at(images, t))["recall"] or 0.0) >= target_recall
    ]
    if reaching:
        return max(reaching), True
    return THRESHOLD_GRID[0], False


def image_level(images: list[ImageResult], threshold: float) -> dict[str, float | int | None]:
    positives = [im for im in images if im.gt]
    negatives = [im for im in images if not im.gt]
    fired = lambda im: any(p.conf >= threshold for p in im.preds)
    hit = sum(1 for im in positives if fired(im))
    false_alarm = sum(1 for im in negatives if fired(im))
    return {
        "images_with_objects": len(positives),
        "images_without_objects": len(negatives),
        "recall": hit / len(positives) if positives else None,
        "false_alarm_rate": false_alarm / len(negatives) if negatives else None,
    }


def calibration(images: list[ImageResult], bins: int = CALIBRATION_BINS) -> dict:
    """Reliability of confidence as P(prediction matches a ground truth box)."""
    rows = [{"low": i / bins, "high": (i + 1) / bins, "n": 0, "conf_sum": 0.0, "tp": 0} for i in range(bins)]
    for image in images:
        for pred in image.preds:
            row = rows[min(int(pred.conf * bins), bins - 1)]
            row["n"] += 1
            row["conf_sum"] += pred.conf
            row["tp"] += pred.matched
    total = sum(r["n"] for r in rows)
    ece = 0.0
    table = []
    for r in rows:
        if not r["n"]:
            table.append({"bin": f"{r['low']:.1f}-{r['high']:.1f}", "n": 0, "mean_conf": None, "precision": None})
            continue
        mean_conf, precision = r["conf_sum"] / r["n"], r["tp"] / r["n"]
        ece += r["n"] / total * abs(mean_conf - precision)
        table.append({"bin": f"{r['low']:.1f}-{r['high']:.1f}", "n": r["n"],
                      "mean_conf": mean_conf, "precision": precision})
    return {"ece": ece if total else None, "predictions": total, "bins": table}


def read_yaml_paths(data_yaml: Path) -> tuple[Path, dict[str, str], list[str]]:
    """Minimal reader for the data.yaml files written by ml/prepare_*.py."""
    text = data_yaml.read_text(encoding="utf-8")
    match = re.search(r'^path:\s*"?([^"\n]+)"?\s*$', text, re.MULTILINE)
    root = Path(match.group(1)) if match else data_yaml.resolve().parent  # Ultralytics' default
    splits = {k: re.search(rf"^{k}:\s*(\S+)\s*$", text, re.MULTILINE).group(1) for k in ("train", "val", "test")}
    names = [m.group(2) for m in re.finditer(r"^\s+(\d+):\s*(\S+)\s*$", text, re.MULTILINE)]
    return root, splits, names


def excluded_images(root: Path, split: str, origins: list[str]) -> set[str]:
    sources = root / "sources.csv"
    if not origins or not sources.exists():
        return set()
    with sources.open(newline="", encoding="utf-8") as fh:
        return {
            Path(row["file"]).name
            for row in csv.DictReader(fh)
            if row["origin"] in origins and row["file"].startswith(f"images/{split}/")
        }


def load_ground_truth(label_path: Path) -> list[tuple[int, tuple[float, float, float, float]]]:
    boxes = []
    if label_path.exists():
        for line in label_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) != 5:
                continue
            cls, xc, yc, w, h = int(parts[0]), *map(float, parts[1:])
            boxes.append((cls, (xc - w / 2, yc - h / 2, xc + w / 2, yc + h / 2)))
    return boxes


def run_predictions(model, root: Path, split_dir: str, skip: set[str], imgsz: int) -> list[ImageResult]:
    image_dir = root / split_dir
    label_dir = root / split_dir.replace("images", "labels", 1)
    paths = sorted(p for p in image_dir.glob("*.jpg") if p.name not in skip)
    results = []
    # Ultralytics runs a list source as a single batch, so a whole split at once runs out
    # of GPU memory with yolo11s on 6 GB. Feed it fixed-size chunks instead.
    for start in range(0, len(paths), PREDICT_BATCH):
        chunk = paths[start:start + PREDICT_BATCH]
        outputs = model.predict(source=[str(p) for p in chunk], conf=CONF_FLOOR, imgsz=imgsz,
                                verbose=False, max_det=300)
        for path, result in zip(chunk, outputs, strict=True):
            boxes = result.boxes
            preds = [
                Prediction(int(c), float(s), tuple(float(v) for v in xyxy))
                for c, s, xyxy in zip(boxes.cls.tolist(), boxes.conf.tolist(), boxes.xyxyn.tolist(), strict=True)
            ]
            image = ImageResult(path.name, load_ground_truth(label_dir / f"{path.stem}.txt"), preds)
            match_image(image)
            results.append(image)
    return results


def save_reliability_diagram(calib: dict, path: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    bins = [b for b in calib["bins"] if b["n"]]
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], linestyle="--", color="#8a8a8a", linewidth=1, label="Hiệu chuẩn hoàn hảo")
    ax.plot([b["mean_conf"] for b in bins], [b["precision"] for b in bins], marker="o",
            color="#0E7C86", linewidth=2, label=f"Model (ECE = {calib['ece']:.3f})")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Confidence trung bình")
    ax.set_ylabel("Tỉ lệ dự đoán đúng (IoU ≥ 0.5)")
    ax.set_title(title)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.3f}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--target-recall", type=float, default=0.8)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--exclude-origin", action="append", default=[])
    parser.add_argument("--out", type=Path, help="default: <run dir>/eval[_suffix]")
    args = parser.parse_args()

    from ultralytics import YOLO

    root, splits, names = read_yaml_paths(args.data)
    model = YOLO(str(args.model))
    suffix = "_" + "_".join(f"no_{o}" for o in args.exclude_origin) if args.exclude_origin else ""
    out = args.out or args.model.parent.parent / f"eval{suffix}"
    out.mkdir(parents=True, exist_ok=True)

    val_images = run_predictions(model, root, splits["val"], excluded_images(root, "val", args.exclude_origin), args.imgsz)
    threshold, reached = choose_threshold(val_images, args.target_recall)
    val_at = prf(counts_at(val_images, threshold))

    test_skip = excluded_images(root, "test", args.exclude_origin)
    test_images = run_predictions(model, root, splits["test"], test_skip, args.imgsz)
    per_class = {}
    for cls, name in enumerate(names):
        counts = counts_at(test_images, threshold, cls)
        per_class[name] = {**counts, **prf(counts)}
    overall_counts = counts_at(test_images, threshold)
    calib = calibration(test_images)

    report = {
        "model": str(args.model),
        "data": str(args.data),
        "excluded_origins": args.exclude_origin,
        "target_recall": args.target_recall,
        "threshold": threshold,
        "target_reached_on_val": reached,
        "val_at_threshold": val_at,
        "test_images": len(test_images),
        "test_box_overall": {**overall_counts, **prf(overall_counts)},
        "test_box_per_class": per_class,
        "test_image_level": image_level(test_images, threshold),
        "test_calibration": calib,
    }

    if not args.exclude_origin:
        metrics = model.val(data=str(args.data), split="test", imgsz=args.imgsz, plots=True,
                            project=str(out.resolve()), name="ultralytics_test", exist_ok=True, verbose=False)
        box = metrics.box
        report["ultralytics_test"] = {
            "mAP50": float(box.map50),
            "mAP50_95": float(box.map),
            "per_class": {
                names[int(c)]: {"mAP50": float(box.ap50[i]), "mAP50_95": float(box.ap[i])}
                for i, c in enumerate(metrics.ap_class_index)
            },
            "plots_dir": str(metrics.save_dir),
        }

    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    save_reliability_diagram(calib, out / "reliability.png", args.model.parent.parent.name)

    print(f"threshold (val recall >= {args.target_recall}): {threshold}  reached={reached}  "
          f"val P={fmt(val_at['precision'])} R={fmt(val_at['recall'])}")
    print(f"test images: {len(test_images)}")
    print(f"{'class':18s} {'gt':>5s} {'P':>6s} {'R':>6s} {'F1':>6s}")
    for name, row in per_class.items():
        print(f"{name:18s} {row['gt']:5d} {fmt(row['precision']):>6s} {fmt(row['recall']):>6s} {fmt(row['f1']):>6s}")
    o = report["test_box_overall"]
    print(f"{'ALL':18s} {o['gt']:5d} {fmt(o['precision']):>6s} {fmt(o['recall']):>6s} {fmt(o['f1']):>6s}")
    il = report["test_image_level"]
    print(f"image-level recall: {fmt(il['recall'])} ({il['images_with_objects']} images with objects)")
    print(f"calibration ECE: {fmt(calib['ece'])} over {calib['predictions']} predictions (conf >= {CONF_FLOOR})")
    if "ultralytics_test" in report:
        u = report["ultralytics_test"]
        print(f"ultralytics test mAP50={u['mAP50']:.3f} mAP50-95={u['mAP50_95']:.3f}")
    print(f"report: {out / 'report.json'}")


if __name__ == "__main__":
    main()
