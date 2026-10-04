import random
from collections import Counter
from pathlib import Path

import prepare_vistext as pv
import pytest
from PIL import Image, ImageEnhance


def _candidate(stem, dhash, counts=None, split="train"):
    return pv.Candidate(split, stem, Path(stem + ".jpg"), dhash, 1, ["0 0.5 0.5 0.1 0.1"],
                        Counter(counts or {"used_tire": 1}))


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("abandoned-tyre-outdoor-still-water-260nw-1925679134_jpg", True),
        ("360_F_416937878_MFUOuT8o49WUiL3Ad7E0pm0SLF5qrlt4_jpg", True),
        ("istockphoto-474711090-612x612_jpg", True),
        ("old-tires-rain-water-breeding-place-aedes-334406430_webp", True),
        ("IMG_20240701_124038_jpg", False),
        ("20240912_182048_jpg", False),
        ("1-2-_jpg", False),
    ],
)
def test_stock_photo_filter(stem, expected):
    assert pv.is_stock_photo(stem) is expected


def test_source_stem_strips_roboflow_suffix():
    path = Path("IMG_20240701_124038_jpg.rf.6d0580a1e5a3825cc064e73ea7fac90b.jpg")
    assert pv.source_stem(path) == "IMG_20240701_124038_jpg"


def test_to_bbox_converts_polygon_and_clips():
    xc, yc, w, h = pv.to_bbox([-0.1, 0.2, 0.5, 0.2, 0.5, 0.6, -0.1, 0.6])
    assert (xc, yc, w, h) == pytest.approx((0.25, 0.4, 0.5, 0.4))
    assert pv.to_bbox([0.5, 0.5, 0.0, 0.2]) is None


def test_to_polygon_turns_box_into_rectangle():
    assert pv.to_polygon([0.5, 0.5, 0.2, 0.4]) == pytest.approx(
        [0.4, 0.3, 0.6, 0.3, 0.6, 0.7, 0.4, 0.7]
    )


def test_convert_labels_remaps_classes():
    task = pv.TASKS[0]
    names = ["Bottle", "Coconut-Exocarp", "Drain-Inlet", "Tire", "Vase"]
    text = "3 0.5 0.5 0.2 0.2\n0 0.1 0.1 0.3 0.1 0.3 0.4\n4 0.5 0.5 0 0\n"
    lines, counts, dropped = pv.convert_labels(text, names, task)
    assert counts == Counter({"used_tire": 1, "plastic_container": 1})
    assert dropped == 1
    assert lines[0].startswith(f"{pv.DETECT_CLASSES.index('used_tire')} ")


def test_collapse_copies_keeps_one_image_per_photo(tmp_path):
    rng = random.Random(0)
    files, stats = [], {}
    for photo in range(2):
        base = Image.new("L", (64, 64))
        base.putdata([rng.randrange(256) for _ in range(64 * 64)])
        for copy, factor in enumerate((0.8, 1.0, 1.2)):
            path = tmp_path / f"photo{photo}_jpg.rf.{copy:032x}.jpg"
            ImageEnhance.Brightness(base.convert("RGB")).enhance(factor).save(path, quality=95)
            files.append(path)
            stats[path] = pv.image_stats(path)
    chosen = pv.collapse_copies(files, stats)
    assert len(chosen) == 2
    assert all(copies == 3 for _, _, copies in chosen)
    assert all(".rf.00000000000000000000000000000001" in p.name for p, _, _ in chosen)


def test_grouping_merges_near_duplicates_and_bursts():
    cands = [
        _candidate("IMG_20240701_124435_jpg", 0b0),
        _candidate("IMG_20240701_124436_jpg", (1 << 200) - 1),  # different look, 1 s later
        _candidate("stock_a", 0b1),                                  # 1 bit from the first
        _candidate("far_away", (1 << 256) - 1),
    ]
    assert pv.group_candidates(cands) == 2
    assert cands[0].group == cands[1].group == cands[2].group != cands[3].group


def test_assign_splits_keeps_groups_together_and_follows_ratios():
    rng = random.Random(1)
    cands = []
    for i in range(300):
        c = _candidate(f"img{i}", rng.getrandbits(256), {"used_tire": 1, "plant_pot": i % 2})
        c.group = i // 3
        cands.append(c)
    pv.assign_splits(cands, seed=7)
    for g in range(100):
        assert len({c.split for c in cands if c.group == g}) == 1
    sizes = Counter(c.split for c in cands)
    assert sizes["train"] == pytest.approx(210, abs=6)
    assert sizes["val"] == pytest.approx(60, abs=6)
    assert sizes["test"] == pytest.approx(30, abs=6)
