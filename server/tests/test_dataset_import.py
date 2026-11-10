from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from edgebench.dataset_import import (
    MAX_SIDE,
    ImportProblem,
    choose_calibration,
    import_directory,
    read_manifest,
)

# Two boxes on a 200 x 100 picture: class 0 at (50, 25) size 40 x 20 pixels, class 2 at (150, 75) size 60 x 40 pixels.
YOLO_ROWS = ["0 0.25 0.25 0.2 0.2", "2 0.75 0.75 0.3 0.4"]


def picture(path: Path, size: tuple[int, int] = (200, 100), colour: tuple[int, int, int] = (200, 30, 30)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, colour).save(path, "JPEG")
    return path


def yolo_folder(root: Path, rows: list[str] | None = None, names: bool = True) -> Path:
    picture(root / "images" / "train" / "a.jpg")
    picture(root / "images" / "train" / "b.jpg", colour=(30, 200, 30))
    (root / "labels" / "train").mkdir(parents=True)
    (root / "labels" / "train" / "a.txt").write_text("\n".join(YOLO_ROWS if rows is None else rows))
    (root / "labels" / "train" / "b.txt").write_text("")  # a labelled picture with nothing in it
    if names:
        (root / "data.yaml").write_text("names:\n  0: chips\n  1: biscuit\n  2: chocolate\n")
    return root


def coco_folder(root: Path) -> Path:
    picture(root / "a.jpg")
    picture(root / "b.jpg", colour=(30, 200, 30))
    data = {
        "images": [
            {"id": 1, "file_name": "a.jpg", "width": 200, "height": 100},
            {"id": 2, "file_name": "b.jpg", "width": 200, "height": 100},
        ],
        # COCO boxes are pixel x, y, width, height from the top left
        "annotations": [
            {"id": 1, "image_id": 1, "category_id": 10, "bbox": [30, 15, 40, 20], "iscrowd": 0},
            {"id": 2, "image_id": 1, "category_id": 30, "bbox": [120, 55, 60, 40], "iscrowd": 0},
        ],
        "categories": [{"id": 30, "name": "chocolate"}, {"id": 10, "name": "chips"}, {"id": 20, "name": "biscuit"}],
    }
    (root / "annotations.json").write_text(json.dumps(data))
    return root


def run(src: Path, tmp_path: Path, **kw: Any) -> tuple[Any, dict[str, Any]]:
    out = tmp_path / f"out-{len(list(tmp_path.glob('out-*')))}.zip"
    result = import_directory(src, out, **kw)
    return result, read_manifest(out)


def test_a_yolo_folder_is_read_with_its_names_and_labels(tmp_path: Path) -> None:
    result, manifest = run(yolo_folder(tmp_path / "set"), tmp_path)
    assert result.format == "yolo" and result.names == ["chips", "biscuit", "chocolate"] and not result.names_generic
    assert (result.image_count, result.labelled_count, result.instance_count) == (2, 2, 2)
    assert result.stats["class_counts"] == [1, 0, 1]
    a = manifest["images"][0]
    assert a["original"] == "images/train/a.jpg" and a["labels"] == [
        [0, 0.25, 0.25, 0.2, 0.2],
        [2, 0.75, 0.75, 0.3, 0.4],
    ]
    assert manifest["images"][1]["labels"] == []


def test_coco_and_yolo_give_the_same_boxes_for_the_same_content(tmp_path: Path) -> None:
    _, yolo = run(yolo_folder(tmp_path / "y"), tmp_path)
    result, coco = run(coco_folder(tmp_path / "c"), tmp_path)
    assert result.format == "coco" and result.names == ["chips", "biscuit", "chocolate"]  # ordered by category id
    got = sorted(coco["images"][0]["labels"])
    want = sorted(yolo["images"][0]["labels"])
    assert len(got) == len(want) == 2
    for g, w in zip(got, want, strict=True):
        assert g == pytest.approx(w, abs=1e-6)
    assert coco["images"][1]["labels"] == []  # listed in the JSON with no boxes: a real empty picture


def test_the_dataset_hash_is_stable_and_changes_when_one_label_changes(tmp_path: Path) -> None:
    first, _ = run(yolo_folder(tmp_path / "one"), tmp_path)
    again, _ = run(yolo_folder(tmp_path / "two"), tmp_path)
    assert first.dataset_hash == again.dataset_hash  # same content in another folder
    changed, _ = run(yolo_folder(tmp_path / "three", rows=["0 0.25 0.25 0.2 0.21", YOLO_ROWS[1]]), tmp_path)
    assert changed.dataset_hash != first.dataset_hash


def test_the_same_dataset_is_the_same_bytes(tmp_path: Path) -> None:
    run(yolo_folder(tmp_path / "one"), tmp_path)
    run(yolo_folder(tmp_path / "two"), tmp_path)
    a, b = sorted(tmp_path.glob("out-*.zip"))
    assert a.read_bytes() == b.read_bytes()


def test_a_big_photo_is_shrunk_but_its_boxes_stay_where_they_were(tmp_path: Path) -> None:
    root = tmp_path / "big"
    picture(root / "images" / "p.jpg", size=(4000, 3000))
    (root / "labels").mkdir()
    (root / "labels" / "p.txt").write_text("0 0.5 0.5 0.25 0.25")
    _, manifest = run(root, tmp_path, names_hint=["thing"])
    im = manifest["images"][0]
    assert max(im["width"], im["height"]) == MAX_SIDE and (im["original_width"], im["original_height"]) == (4000, 3000)
    assert im["labels"] == [[0, 0.5, 0.5, 0.25, 0.25]]


def test_exif_rotation_is_applied_and_reported(tmp_path: Path) -> None:
    root = tmp_path / "rot"
    path = root / "images" / "p.jpg"
    path.parent.mkdir(parents=True)
    img = Image.new("RGB", (200, 100), (10, 10, 200))
    exif = Image.Exif()
    exif[0x0112] = 6  # "rotate 90 degrees to display"
    img.save(path, "JPEG", exif=exif)
    result, manifest = run(root, tmp_path)
    assert (manifest["images"][0]["width"], manifest["images"][0]["height"]) == (100, 200)
    assert any("EXIF rotation" in w for w in result.stats["warnings"])


def test_capture_source_comes_from_a_csv_then_a_folder_name_then_exif(tmp_path: Path) -> None:
    root = tmp_path / "src"
    picture(root / "rpi-cam3-wide" / "a.jpg")
    picture(root / "Mobile" / "b.jpg")
    picture(root / "loose" / "c.jpg")
    picture(root / "loose" / "d.jpg")
    phone = root / "loose" / "e.jpg"
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = "Google", "Pixel 8"
    Image.new("RGB", (50, 50)).save(phone, "JPEG", exif=exif)
    (root / "sources.csv").write_text("file,source\nloose/d.jpg,rpi-cam3-wide\n")
    result, manifest = run(root, tmp_path)
    by_file = {im["original"]: im["source"] for im in manifest["images"]}
    assert by_file == {
        "Mobile/b.jpg": "mobile",
        "loose/c.jpg": "other",
        "loose/d.jpg": "rpi-cam3-wide",  # the csv decides
        "loose/e.jpg": "mobile",  # a camera make in the EXIF
        "rpi-cam3-wide/a.jpg": "rpi-cam3-wide",
    }
    assert {s: v["images"] for s, v in result.stats["sources"].items()} == {"mobile": 2, "other": 1, "rpi-cam3-wide": 2}


def test_pictures_without_labels_are_allowed_and_say_so(tmp_path: Path) -> None:
    root = tmp_path / "plain"
    picture(root / "a.jpg")
    result, manifest = run(root, tmp_path)
    assert result.labelled_count == 0 and manifest["images"][0]["labels"] is None
    assert any("speed runs only" in w for w in result.stats["warnings"])


def test_without_class_names_the_models_names_are_used_or_placeholders_are_made(tmp_path: Path) -> None:
    root = yolo_folder(tmp_path / "set", names=False)
    result, _ = run(root, tmp_path)
    assert result.names == ["class_0", "class_1", "class_2"] and result.names_generic
    result, _ = run(root, tmp_path, names_hint=["chips", "biscuit", "chocolate"])
    assert result.names == ["chips", "biscuit", "chocolate"] and not result.names_generic


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        (["0 0.5 0.5 0.2"], "expected 5 numbers"),
        (["x 0.5 0.5 0.2 0.2"], "expected numbers"),
        (["1.5 0.5 0.5 0.2 0.2"], "whole number"),
        (["0 5 5 2 2"], "between 0 and 1"),
        (["0 0.5 0.5 0 0.2"], "between 0 and 1"),
        (["7 0.5 0.5 0.2 0.2"], "class 7"),
    ],
)
def test_a_bad_label_stops_the_import_and_names_the_line(tmp_path: Path, rows: list[str], message: str) -> None:
    with pytest.raises(ImportProblem, match=message):
        run(yolo_folder(tmp_path / "bad", rows=rows), tmp_path)


def test_a_folder_without_images_and_a_broken_image_are_refused(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "notes.txt").write_text("hello")
    with pytest.raises(ImportProblem, match="No images were found"):
        run(tmp_path / "empty", tmp_path)
    (tmp_path / "heic").mkdir()
    (tmp_path / "heic" / "p.heic").write_bytes(b"x")
    with pytest.raises(ImportProblem, match="HEIC"):
        run(tmp_path / "heic", tmp_path)
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "p.jpg").write_bytes(b"this is not a picture")
    with pytest.raises(ImportProblem, match=r"p\.jpg could not be read"):
        run(tmp_path / "broken", tmp_path)
    assert not list(tmp_path.glob("out-*.zip")) or all(zipfile.is_zipfile(p) for p in tmp_path.glob("out-*.zip"))


def test_a_failed_import_leaves_no_half_written_zip(tmp_path: Path) -> None:
    root = tmp_path / "half"
    picture(root / "a.jpg")
    (root / "b.jpg").write_bytes(b"not a picture")
    out = tmp_path / "half.zip"
    with pytest.raises(ImportProblem):
        import_directory(root, out)
    assert not out.exists()


def sample(n: int, sources: dict[str, int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for source, count in sources.items():
        out += [{"original": f"{source}/{i}.jpg", "source": source} for i in range(count)]
    assert len(out) == n
    return out


def test_the_calibration_subset_is_seeded_mixes_sources_and_has_a_floor(tmp_path: Path) -> None:
    images = sample(300, {"mobile": 250, "rpi-cam3-wide": 50})
    a, b = choose_calibration(images, 100, seed=7), choose_calibration(images, 100, seed=7)
    assert a == b and a["count"] == 100 and len(set(a["files"])) == 100
    assert sum(f.startswith("rpi-cam3-wide/") for f in a["files"]) == 50  # alternates, so the scarce source is fully in
    assert choose_calibration(images, 100, seed=8)["files"] != a["files"]
    assert choose_calibration(images, 10)["count"] == 50  # never under the floor
    assert choose_calibration(images)["count"] == 200  # the default
    with pytest.raises(ImportProblem, match="at least 50"):
        choose_calibration(sample(49, {"mobile": 49}))


def test_an_upright_jpeg_is_stored_as_it_came_and_anything_else_is_converted(tmp_path: Path) -> None:
    """Re-encoding a JPEG shifts detections slightly (measured: about 0.006 mAP50-95 on COCO128), so it is avoided."""
    root = tmp_path / "mix"
    picture(root / "keep.jpg")
    Image.new("RGB", (60, 40), (1, 2, 3)).save(root / "from_png.png")
    result, manifest = run(root, tmp_path)
    with zipfile.ZipFile(next(tmp_path.glob("out-*.zip"))) as z:
        kept = next(m for m in manifest["images"] if m["original"] == "keep.jpg")
        assert z.read(kept["file"]) == (root / "keep.jpg").read_bytes()
        converted = next(m for m in manifest["images"] if m["original"] == "from_png.png")
        assert z.read(converted["file"])[:3] == b"\xff\xd8\xff"  # a PNG became a JPEG
    assert result.image_count == 2
