"""Prepare the VisText-Mosquito dataset for AquaPulse YOLO training.

Source: Mendeley Data rtsfh7jh7p v2 (CC BY 4.0), downloaded and extracted to
data/raw/vistext-mosquito/extracted.

Outputs:
  data/{images,labels}/{train,val,test} + data/data.yaml                  detection
  data/water_seg/{images,labels}/{train,val,test} + data/water_seg/data.yaml  segmentation
  data/sources.csv   one row per kept image (origin, license, attribution)
  data/excluded.csv  one row per dropped image and the reason

Steps:
  1. Drop stock-photo previews (unless --keep-stock) (Shutterstock, Adobe Stock, iStock, ...): the
     uploader could not relicense them and they often carry watermarks.
  2. Collapse Roboflow's 3x brightness augmentation back to one image per photo.
     Ultralytics augments during training, so the copies only inflate counts.
  3. Drop exact duplicates and remap source classes to AquaPulse classes.
  4. Re-split into train/val/test by groups of near-duplicate photos and
     burst shots, so the same scene never lands in two splits.

Usage: python ml/prepare_vistext.py [--raw DIR] [--out DIR] [--seed N] [--keep-stock]

--keep-stock keeps the stock previews (marked origin=stock_photo_preview). About 97%
of the source Tire labels are on stock images, so without it used_tire is nearly empty.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import random
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from itertools import combinations, pairwise
from pathlib import Path

from classes import DETECT_CLASSES, WATER_SEG_CLASSES
from PIL import Image, ImageStat

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RAW = REPO_ROOT / "data" / "raw" / "vistext-mosquito" / "extracted"
DEFAULT_OUT = REPO_ROOT / "data"

SOURCE_ID = "vistext-mosquito"
LICENSE = "CC BY 4.0"
ATTRIBUTION = (
    "VisText-Mosquito: A Multimodal Dataset for Mosquito Breeding Site Detection, "
    "Surface Segmentation, and Reasoning. Mendeley Data, V2, doi:10.17632/rtsfh7jh7p.2"
)
SOURCE_URL = "https://data.mendeley.com/datasets/rtsfh7jh7p/2"
OUTPUT_PREFIX = "vistext_"

SOURCE_SPLITS = ("train", "valid", "test")
SPLIT_RATIOS = {"train": 0.7, "val": 0.2, "test": 0.1}

# dHash distance (out of 256 bits) under which two images count as the same scene.
NEAR_DUPLICATE_BITS = 12
# Distance under which two images are the same picture (one is dropped).
EXACT_DUPLICATE_BITS = 2
# Phone photos taken this close together are treated as one scene. The source photos
# come in rapid bursts; 60 s chained whole photo walks into one 489-image group.
BURST_SECONDS = 5

ROBOFLOW_SUFFIX = re.compile(r"\.rf\.[0-9a-f]{32}$")
STOCK_PATTERN = re.compile(
    r"260nw-\d+|^360_F_\d+|istockphoto|shutterstock|adobestock|depositphotos|dreamstime"
    r"|gettyimages|freepik|pngtree|alamy|-\d{8,9}(-\d-)?_webp$",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"^(?:IMG_)?(\d{8})_(\d{6})")


@dataclass(frozen=True)
class TaskSpec:
    name: str
    source_dir: str
    class_map: dict[str, str]
    classes: list[str]
    label_kind: str  # "bbox" or "polygon"
    out_subdir: str


TASKS = (
    TaskSpec(
        name="detect",
        source_dir="Breeding Place Detection",
        class_map={
            "Bottle": "plastic_container",
            "Coconut-Exocarp": "coconut_shell",
            "Drain-Inlet": "drain_inlet",
            "Tire": "used_tire",
            "Vase": "plant_pot",
        },
        classes=DETECT_CLASSES,
        label_kind="bbox",
        out_subdir="",
    ),
    TaskSpec(
        name="water_seg",
        source_dir="Water Surface Segmentation",
        class_map={"tire_with_water": "water", "vase_with_water": "water"},
        classes=WATER_SEG_CLASSES,
        label_kind="polygon",
        out_subdir="water_seg",
    ),
)

SOURCES_FIELDS = [
    "file", "task", "split", "source_dataset", "original_file", "original_split",
    "origin", "scene_group", "instances", "license", "attribution", "url",
]
EXCLUDED_FIELDS = ["source_dataset", "task", "original_split", "original_file", "reason"]


@dataclass
class Candidate:
    original_split: str
    stem: str
    image: Path
    dhash: int
    copies: int
    lines: list[str] = field(default_factory=list)
    class_counts: Counter = field(default_factory=Counter)
    group: int = -1
    split: str = ""


def long_path(path: Path) -> str:
    """Windows refuses paths over 260 chars unless they use the extended prefix."""
    text = str(path.resolve())
    if sys.platform == "win32" and len(text) >= 240 and not text.startswith("\\\\?\\"):
        return "\\\\?\\" + text
    return text


def source_stem(path: Path) -> str:
    return ROBOFLOW_SUFFIX.sub("", path.stem)


def is_stock_photo(stem: str) -> bool:
    return bool(STOCK_PATTERN.search(stem))


def phone_timestamp(stem: str) -> datetime | None:
    match = PHONE_PATTERN.match(stem)
    if not match:
        return None
    try:
        # Naive on purpose: only differences between photos from the same camera are used.
        return datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")  # noqa: DTZ007
    except ValueError:
        return None


def origin_of(stem: str) -> str:
    if is_stock_photo(stem):
        return "stock_photo_preview"
    return "phone_photo" if phone_timestamp(stem) else "unknown"


def image_stats(path: Path) -> tuple[int, float]:
    """Return (256-bit difference hash, mean luminance)."""
    with open(long_path(path), "rb") as fh, Image.open(fh) as im:
        gray = im.convert("L")
        luma = ImageStat.Stat(gray).mean[0]
        small = gray.resize((17, 16), Image.Resampling.LANCZOS).tobytes()
    bits = 0
    for row in range(16):
        for col in range(16):
            if small[row * 17 + col] > small[row * 17 + col + 1]:
                bits |= 1 << (row * 16 + col)
    return bits, luma


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def collapse_copies(
    files: list[Path], stats: dict[Path, tuple[int, float]], max_bits: int = NEAR_DUPLICATE_BITS
) -> list[tuple[Path, int, int]]:
    """Group augmented copies of one photo; return (chosen file, dhash, copy count).

    Copies share a Roboflow stem and look alike. Different photos can share a stem
    too, so copies are also clustered by hash. The copy with the median brightness
    is kept as the least altered one.
    """
    by_stem: dict[str, list[Path]] = {}
    for path in sorted(files):
        by_stem.setdefault(source_stem(path), []).append(path)

    chosen = []
    for paths in by_stem.values():
        clusters: list[list[Path]] = []
        for path in paths:
            for cluster in clusters:
                if hamming(stats[cluster[0]][0], stats[path][0]) <= max_bits:
                    cluster.append(path)
                    break
            else:
                clusters.append([path])
        for cluster in clusters:
            by_luma = sorted(cluster, key=lambda p: stats[p][1])
            pick = by_luma[len(by_luma) // 2]
            chosen.append((pick, stats[pick][0], len(cluster)))
    return chosen


def read_source_names(data_yaml: Path) -> list[str]:
    match = re.search(r"^names:\s*(\[.*\])\s*$", data_yaml.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise ValueError(f"No names list in {data_yaml}")
    return list(ast.literal_eval(match.group(1)))


def clip01(value: float) -> float:
    return min(1.0, max(0.0, value))


def to_bbox(coords: list[float]) -> tuple[float, float, float, float] | None:
    """Convert a YOLO box or polygon to a clipped (xc, yc, w, h) box, or None if degenerate."""
    if len(coords) == 4:
        xc, yc, w, h = coords
        x0, y0, x1, y1 = xc - w / 2, yc - h / 2, xc + w / 2, yc + h / 2
    else:
        xs, ys = coords[0::2], coords[1::2]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    x0, y0, x1, y1 = clip01(x0), clip01(y0), clip01(x1), clip01(y1)
    if x1 - x0 <= 1e-4 or y1 - y0 <= 1e-4:
        return None
    return (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0


def to_polygon(coords: list[float]) -> list[float] | None:
    """Convert a YOLO polygon (or box) to a clipped polygon, or None if degenerate."""
    if len(coords) == 4:
        xc, yc, w, h = coords
        coords = [xc - w / 2, yc - h / 2, xc + w / 2, yc - h / 2,
                  xc + w / 2, yc + h / 2, xc - w / 2, yc + h / 2]
    if len(coords) < 6 or len(coords) % 2:
        return None
    points = [clip01(v) for v in coords]
    if to_bbox(points) is None:
        return None
    return points


def convert_labels(
    text: str, source_names: list[str], task: TaskSpec
) -> tuple[list[str], Counter, int]:
    """Remap one label file. Returns (output lines, class counts, dropped degenerate shapes)."""
    lines, counts, dropped = [], Counter(), 0
    for raw_line in text.splitlines():
        parts = raw_line.split()
        if not parts:
            continue
        source_class = source_names[int(parts[0])]
        target = task.class_map[source_class]
        coords = [float(v) for v in parts[1:]]
        shape = to_bbox(coords) if task.label_kind == "bbox" else to_polygon(coords)
        if shape is None:
            dropped += 1
            continue
        class_id = task.classes.index(target)
        lines.append(f"{class_id} " + " ".join(f"{v:.6f}" for v in shape))
        counts[target] += 1
    return lines, counts, dropped


def group_candidates(
    candidates: list[Candidate],
    near_bits: int = NEAR_DUPLICATE_BITS,
    burst_seconds: int = BURST_SECONDS,
) -> int:
    """Assign candidate.group so near-duplicates and burst shots share a group. Returns group count."""
    parent = list(range(len(candidates)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    for i, j in combinations(range(len(candidates)), 2):
        if hamming(candidates[i].dhash, candidates[j].dhash) <= near_bits:
            union(i, j)

    timed = sorted(
        (ts, i) for i, c in enumerate(candidates) if (ts := phone_timestamp(c.stem)) is not None
    )
    for (t1, i1), (t2, i2) in pairwise(timed):
        if (t2 - t1).total_seconds() <= burst_seconds:
            union(i1, i2)

    roots = sorted({find(i) for i in range(len(candidates))}, key=lambda r: candidates[r].stem)
    group_ids = {root: n for n, root in enumerate(roots)}
    for i, candidate in enumerate(candidates):
        candidate.group = group_ids[find(i)]
    return len(roots)


def assign_splits(
    candidates: list[Candidate], ratios: dict[str, float] = SPLIT_RATIOS, seed: int = 42
) -> None:
    """Greedy group-level split that tracks both image counts and per-class instance counts."""
    groups: dict[int, list[Candidate]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.group, []).append(candidate)

    order = sorted(groups)
    random.Random(seed).shuffle(order)
    order.sort(key=lambda g: -len(groups[g]))  # stable: large groups first, ties stay shuffled

    total_images = len(candidates)
    class_totals: Counter = Counter()
    for candidate in candidates:
        class_totals.update(candidate.class_counts)

    images = {s: 0 for s in ratios}
    instances = {s: Counter() for s in ratios}
    for gid in order:
        members = groups[gid]
        group_counts: Counter = Counter()
        for candidate in members:
            group_counts.update(candidate.class_counts)

        def need(split: str, group_counts: Counter = group_counts) -> float:
            score = (ratios[split] * total_images - images[split]) / total_images
            for cls in group_counts:
                score += (ratios[split] * class_totals[cls] - instances[split][cls]) / class_totals[cls]
            return score

        split = max(ratios, key=need)
        images[split] += len(members)
        instances[split].update(group_counts)
        for candidate in members:
            candidate.split = split


def cross_split_near_duplicates(
    candidates: list[Candidate], near_bits: int = NEAR_DUPLICATE_BITS
) -> int:
    return sum(
        1
        for a, b in combinations(candidates, 2)
        if a.split != b.split and hamming(a.dhash, b.dhash) <= near_bits
    )


def remove_previous_outputs(out_dir: Path) -> None:
    for kind in ("images", "labels"):
        for split in SPLIT_RATIOS:
            directory = out_dir / kind / split
            if directory.is_dir():
                for path in directory.glob(OUTPUT_PREFIX + "*"):
                    path.unlink()


def write_data_yaml(out_dir: Path, classes: list[str], script_name: str) -> None:
    names = "\n".join(f"  {i}: {name}" for i, name in enumerate(classes))
    (out_dir / "data.yaml").write_text(
        f"# Generated by ml/{script_name}. No `path` key on purpose: Ultralytics then uses\n"
        "# this file's folder as the dataset root, which works on any machine and in Docker.\n"
        "train: images/train\n"
        "val: images/val\n"
        "test: images/test\n"
        f"names:\n{names}\n",
        encoding="utf-8",
    )


def merge_csv(path: Path, fields: list[str], new_rows: list[dict]) -> None:
    """Replace this source's rows in a CSV shared with other dataset sources."""
    rows = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as fh:
            rows = [row for row in csv.DictReader(fh) if row.get("source_dataset") != SOURCE_ID]
    rows.extend(new_rows)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def prepare_task(task: TaskSpec, raw_root: Path, out_root: Path, seed: int, keep_stock: bool):
    source_root = raw_root / task.source_dir
    source_names = read_source_names(source_root / "data.yaml")
    unknown = set(source_names) - set(task.class_map)
    if unknown:
        raise ValueError(f"{task.name}: no AquaPulse class mapped for {sorted(unknown)}")

    excluded: list[dict] = []

    def exclude(original_split: str, original_file: str, reason: str) -> None:
        excluded.append({
            "source_dataset": SOURCE_ID, "task": task.name, "original_split": original_split,
            "original_file": original_file, "reason": reason,
        })

    candidates: list[Candidate] = []
    raw_files = 0
    dropped_shapes = 0
    for original_split in SOURCE_SPLITS:
        image_dir = source_root / original_split / "images"
        label_dir = source_root / original_split / "labels"
        files = sorted(image_dir.glob("*"))
        raw_files += len(files)

        kept_files = []
        stock_stems = set()
        for path in files:
            stem = source_stem(path)
            if is_stock_photo(stem) and not keep_stock:
                stock_stems.add(stem)
            else:
                kept_files.append(path)
        for stem in sorted(stock_stems):
            exclude(original_split, stem, "stock_photo_preview")

        stats = {path: image_stats(path) for path in kept_files}
        for path, dhash, copies in collapse_copies(kept_files, stats):
            stem = source_stem(path)
            label_path = label_dir / (path.stem + ".txt")
            if not Path(long_path(label_path)).exists():
                exclude(original_split, path.name, "missing_label_file")
                continue
            with open(long_path(label_path), encoding="utf-8") as fh:
                text = fh.read()
            lines, counts, dropped = convert_labels(text, source_names, task)
            dropped_shapes += dropped
            if text.strip() and not lines:
                exclude(original_split, path.name, "no_valid_shapes")
                continue
            candidates.append(Candidate(original_split, stem, path, dhash, copies, lines, counts))

    unique: list[Candidate] = []
    for candidate in candidates:
        twin = next(
            (u for u in unique if hamming(u.dhash, candidate.dhash) <= EXACT_DUPLICATE_BITS), None
        )
        if twin is None:
            unique.append(candidate)
        else:
            exclude(candidate.original_split, candidate.image.name, f"duplicate_of:{twin.image.name}")

    group_count = group_candidates(unique)
    assign_splits(unique, seed=seed)

    out_dir = out_root / task.out_subdir if task.out_subdir else out_root
    remove_previous_outputs(out_dir)
    for kind in ("images", "labels"):
        for split in SPLIT_RATIOS:
            (out_dir / kind / split).mkdir(parents=True, exist_ok=True)

    sources: list[dict] = []
    for candidate in sorted(unique, key=lambda c: (c.split, c.group, c.stem)):
        with open(long_path(candidate.image), "rb") as fh:
            data = fh.read()
        name = f"{OUTPUT_PREFIX}{hashlib.sha256(data).hexdigest()[:16]}"
        (out_dir / "images" / candidate.split / f"{name}.jpg").write_bytes(data)
        label_text = "\n".join(candidate.lines) + ("\n" if candidate.lines else "")
        (out_dir / "labels" / candidate.split / f"{name}.txt").write_text(label_text, encoding="utf-8")
        sources.append({
            "file": f"{(out_dir / 'images' / candidate.split / name).relative_to(out_root).as_posix()}.jpg",
            "task": task.name,
            "split": candidate.split,
            "source_dataset": SOURCE_ID,
            "original_file": candidate.image.name,
            "original_split": candidate.original_split,
            "origin": origin_of(candidate.stem),
            "scene_group": f"{task.name}-{candidate.group}",
            "instances": sum(candidate.class_counts.values()),
            "license": LICENSE,
            "attribution": ATTRIBUTION,
            "url": SOURCE_URL,
        })

    write_data_yaml(out_dir, task.classes, Path(__file__).name)
    print_summary(task, raw_files, unique, excluded, group_count, dropped_shapes)
    return sources, excluded


def print_summary(task, raw_files, candidates, excluded, group_count, dropped_shapes) -> None:
    print(f"\n=== {task.name} ({task.source_dir})")
    print(f"raw files: {raw_files}  ->  kept images: {len(candidates)} in {group_count} scene groups")
    reasons = Counter(row["reason"].split(":")[0] for row in excluded)
    print(f"excluded: {dict(reasons)}")
    print(f"degenerate shapes dropped: {dropped_shapes}")
    print(f"augmented copies collapsed: {sum(c.copies - 1 for c in candidates)}")
    header = f"{'split':6s} {'images':>6s} {'background':>10s} " + " ".join(
        f"{name[:12]:>12s}" for name in task.classes
    )
    print(header)
    for split in SPLIT_RATIOS:
        members = [c for c in candidates if c.split == split]
        counts: Counter = Counter()
        for c in members:
            counts.update(c.class_counts)
        background = sum(1 for c in members if not c.lines)
        print(f"{split:6s} {len(members):6d} {background:10d} " + " ".join(
            f"{counts[name]:12d}" for name in task.classes
        ))
    print(f"near-duplicate pairs across splits: {cross_split_near_duplicates(candidates)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--keep-stock", action="store_true", help="keep stock-photo previews")
    args = parser.parse_args()

    if not args.raw.is_dir():
        sys.exit(f"Raw dataset not found: {args.raw}")

    all_sources, all_excluded = [], []
    for task in TASKS:
        sources, excluded = prepare_task(task, args.raw, args.out, args.seed, args.keep_stock)
        all_sources.extend(sources)
        all_excluded.extend(excluded)

    merge_csv(args.out / "sources.csv", SOURCES_FIELDS, all_sources)
    merge_csv(args.out / "excluded.csv", EXCLUDED_FIELDS, all_excluded)
    print(f"\nWrote {len(all_sources)} rows to sources.csv, {len(all_excluded)} rows to excluded.csv")


if __name__ == "__main__":
    main()
