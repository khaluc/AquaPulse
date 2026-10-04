import evaluate as ev
import pytest


def _image(gt, preds):
    image = ev.ImageResult("x.jpg", gt, [ev.Prediction(c, s, b) for c, s, b in preds])
    ev.match_image(image)
    return image


BOX = (0.1, 0.1, 0.5, 0.5)
SHIFTED = (0.12, 0.12, 0.52, 0.52)
FAR = (0.6, 0.6, 0.9, 0.9)


def test_iou():
    assert ev.iou(BOX, BOX) == pytest.approx(1.0)
    assert ev.iou(BOX, FAR) == 0.0


def test_matching_requires_class_and_one_prediction_per_ground_truth():
    image = _image([(0, BOX)], [(0, 0.9, SHIFTED), (0, 0.8, BOX), (1, 0.95, BOX)])
    by_conf = {p.conf: p.matched for p in image.preds}
    assert by_conf == {0.9: True, 0.8: False, 0.95: False}


def test_counts_and_prf_at_threshold():
    images = [
        _image([(0, BOX)], [(0, 0.9, BOX), (0, 0.3, FAR)]),
        _image([(1, BOX)], [(1, 0.2, BOX)]),
    ]
    assert ev.counts_at(images, 0.5) == {"tp": 1, "fp": 0, "fn": 1, "gt": 2}
    assert ev.counts_at(images, 0.1) == {"tp": 2, "fp": 1, "fn": 0, "gt": 2}
    assert ev.prf(ev.counts_at(images, 0.1))["precision"] == pytest.approx(2 / 3)
    assert ev.counts_at(images, 0.1, cls=1) == {"tp": 1, "fp": 0, "fn": 0, "gt": 1}


def test_choose_threshold_is_highest_reaching_target():
    images = [
        _image([(0, BOX)], [(0, 0.72, BOX)]),
        _image([(0, BOX)], [(0, 0.33, BOX)]),
    ]
    assert ev.choose_threshold(images, 1.0) == (0.3, True)
    assert ev.choose_threshold(images, 0.5) == (0.7, True)
    assert ev.choose_threshold([_image([(0, BOX)], [])], 0.5) == (0.05, False)


def test_image_level_recall_and_false_alarms():
    images = [
        _image([(0, BOX)], [(0, 0.9, FAR)]),  # fires (wrong place still counts at image level)
        _image([(0, BOX)], [(0, 0.1, BOX)]),  # below threshold
        _image([], [(0, 0.6, BOX)]),          # background with a false alarm
    ]
    assert ev.image_level(images, 0.5) == {
        "images_with_objects": 2, "images_without_objects": 1, "recall": 0.5, "false_alarm_rate": 1.0,
    }


def test_calibration_ece():
    images = [_image([(0, BOX)], [(0, 0.95, BOX), (0, 0.95, FAR)])]
    calib = ev.calibration(images)
    assert calib["predictions"] == 2
    assert calib["ece"] == pytest.approx(0.45)


def test_read_yaml_paths(tmp_path):
    yaml = tmp_path / "data.yaml"
    yaml.write_text('path: "D:/x y/data"\ntrain: images/train\nval: images/val\ntest: images/test\n'
                    "names:\n  0: used_tire\n  1: plant_pot\n", encoding="utf-8")
    root, splits, names = ev.read_yaml_paths(yaml)
    assert root.as_posix() == "D:/x y/data"
    assert splits["test"] == "images/test"
    assert names == ["used_tire", "plant_pot"]


def test_read_yaml_paths_defaults_root_to_yaml_folder(tmp_path):
    yaml = tmp_path / "data.yaml"
    yaml.write_text("train: images/train\nval: images/val\ntest: images/test\nnames:\n  0: water\n",
                    encoding="utf-8")
    root, _, names = ev.read_yaml_paths(yaml)
    assert root == tmp_path.resolve()
    assert names == ["water"]
