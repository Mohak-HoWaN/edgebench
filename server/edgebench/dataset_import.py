"""Turn a folder of images (YOLO or COCO) into one normalised dataset zip that the agents and the previews read.

The zip holds ``data.json`` and ``images/NNNNNN.jpg``. Every image is rotated by its EXIF orientation, converted to RGB
JPEG and capped at ``MAX_SIDE`` on its long side (a 12 MP phone photo becomes about 2 MP), once, here. Labels are stored
normalised (class, centre x, centre y, width, height), so shrinking an image never moves a box. The hash of each
original file is recorded, and the dataset hash is taken over the originals and their labels, not over the re-encoded
copies.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from PIL import Image, ImageOps, UnidentifiedImageError

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
HEIC_EXTENSIONS = {".heic", ".heif"}
MAX_SIDE = 1920
JPEG_QUALITY = 95
FIXED_TIME = (2026, 1, 1, 0, 0, 0)  # a zip stores times; a fixed one keeps the same dataset byte-identical
SOURCE_TAGS = {
    "rpi-cam3-wide": "rpi-cam3-wide",
    "rpi-cam3": "rpi-cam3-wide",
    "rpi": "rpi-cam3-wide",
    "picam": "rpi-cam3-wide",
    "mobile": "mobile",
    "phone": "mobile",
}
RESOLUTION_BUCKETS = (
    (0.5, "under 0.5 MP"),
    (1, "0.5 to 1 MP"),
    (2, "1 to 2 MP"),
    (4, "2 to 4 MP"),
    (12.5, "4 to 12 MP"),
)
MIN_CALIBRATION = 50
DEFAULT_CALIBRATION = 200


class ImportProblem(Exception):
    """The folder cannot be imported; the message says why in words fit for the person using the tool."""


@dataclass
class ImportResult:
    format: str
    names: list[str]
    names_generic: bool
    image_count: int
    labelled_count: int
    instance_count: int
    dataset_hash: str
    stats: dict[str, Any]
    size_bytes: int = 0


@dataclass
class _Item:
    path: Path
    rel: str
    labels: list[list[float]] | None = None
    source: str = "other"
    sha: str = ""
    width: int = 0
    height: int = 0


def _label_hash(labels: list[list[float]] | None) -> str:
    if labels is None:
        return "-"
    lines = (" ".join(str(int(v)) if i == 0 else f"{v:.6f}" for i, v in enumerate(row)) for row in labels)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


# --- labels -----------------------------------------------------------------------------------------------------------


def _parse_yolo_label(text: str, where: str) -> list[list[float]]:
    rows: list[list[float]] = []
    for number, line in enumerate(text.splitlines(), 1):
        parts = line.split()
        if not parts:
            continue
        try:
            values = [float(p) for p in parts]
        except ValueError:
            raise ImportProblem(f"{where} line {number}: expected numbers, found {line[:40]!r}.") from None
        cls = values[0]
        if cls != int(cls) or cls < 0:
            raise ImportProblem(f"{where} line {number}: the class must be a whole number from 0 up, found {parts[0]}.")
        if len(values) == 5:
            cx, cy, w, h = values[1:]
        elif len(values) > 5 and len(values) % 2 == 1:  # a segmentation polygon: use its bounding box
            xs, ys = values[1::2], values[2::2]
            cx, cy, w, h = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs), max(ys) - min(ys)
        else:
            raise ImportProblem(f"{where} line {number}: expected 5 numbers (class x y w h), found {len(values)}.")
        if max(abs(cx), abs(cy), w, h) > 1.01 or w <= 0 or h <= 0 or cx < 0 or cy < 0:
            raise ImportProblem(f"{where} line {number}: box values must be between 0 and 1 (relative to the image).")
        rows.append([float(int(cls)), min(cx, 1.0), min(cy, 1.0), min(w, 1.0), min(h, 1.0)])
    return rows


def _yolo_label_path(src: Path, image: Path) -> Path | None:
    rel = image.relative_to(src)
    parts = list(rel.parts[:-1])
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "images":
            candidate = src.joinpath(*parts[:i], "labels", *parts[i + 1 :], rel.stem + ".txt")
            if candidate.is_file():
                return candidate
            break
    sibling = image.with_suffix(".txt")
    return sibling if sibling.is_file() else None


def _read_yaml_names(src: Path) -> list[str] | None:
    for path in [*sorted(src.glob("*.y*ml")), *sorted(src.glob("*/*.y*ml"))]:
        if path.suffix not in (".yaml", ".yml"):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError, UnicodeDecodeError):
            continue
        names = data.get("names") if isinstance(data, dict) else None
        if isinstance(names, list) and names:
            return [str(n) for n in names]
        if isinstance(names, dict) and names:
            try:
                return [str(v) for _, v in sorted(names.items(), key=lambda kv: int(kv[0]))]
            except (TypeError, ValueError):
                continue
    for name in ("classes.txt", "obj.names", "labels.txt"):
        path = src / name
        if path.is_file():
            lines = [ln.strip() for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
            if lines:
                return lines
    return None


def _find_coco_json(src: Path) -> Path | None:
    for path in sorted(src.rglob("*.json")):
        if path.stat().st_size > 512 * 1024**2:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and {"images", "annotations", "categories"} <= data.keys():
            return path
    return None


def _match_coco_file(
    items: list[_Item], coco_path: Path, file_name: str, by_base: dict[str, list[_Item]]
) -> _Item | None:
    for it in items:
        if it.path == coco_path.parent / file_name or it.rel == file_name or it.rel.endswith("/" + file_name):
            return it
    candidates = by_base.get(Path(file_name).name, [])
    return candidates[0] if len(candidates) == 1 else None


def _coco_box(ann: dict[str, Any], width: int, height: int) -> list[float] | None:
    x, y, bw, bh = (float(v) for v in ann["bbox"])
    x1, y1, x2, y2 = max(x, 0.0), max(y, 0.0), min(x + bw, width), min(y + bh, height)
    if x2 <= x1 or y2 <= y1:
        return None
    return [(x1 + x2) / 2 / width, (y1 + y2) / 2 / height, (x2 - x1) / width, (y2 - y1) / height]


def _attach_coco(items: list[_Item], coco_path: Path) -> list[str]:
    """Give each image its boxes from a COCO JSON file. Returns the class names, ordered by category id."""
    data = json.loads(coco_path.read_text(encoding="utf-8"))
    cats = sorted(data["categories"], key=lambda c: c["id"])
    index = {c["id"]: i for i, c in enumerate(cats)}
    by_base: dict[str, list[_Item]] = {}
    for it in items:
        by_base.setdefault(Path(it.rel).name, []).append(it)
    declared: dict[int, tuple[_Item, int, int]] = {}
    for entry in data["images"]:
        found = _match_coco_file(items, coco_path, str(entry["file_name"]).replace("\\", "/"), by_base)
        if found is None:
            continue
        width, height = entry.get("width"), entry.get("height")
        if not (width and height):
            with Image.open(found.path) as im:
                width, height = im.size
        declared[entry["id"]] = (found, int(width), int(height))
        found.labels = []  # a COCO file lists every image, so one without annotations is a real empty image
    if not declared:
        raise ImportProblem("The COCO file lists no image that could be found in the folder (matched by file name).")
    for ann in data["annotations"]:
        target = declared.get(ann["image_id"])
        if target is None or ann["category_id"] not in index or ann.get("iscrowd"):
            continue
        item, width, height = target
        box = _coco_box(ann, width, height)
        if box is not None and item.labels is not None:
            item.labels.append([float(index[ann["category_id"]]), *box])
    return [str(c["name"]) for c in cats]


def _voc_files(src: Path) -> list[Path]:
    """Pascal VOC annotation files: XML whose root is <annotation> (no external entities are fetched)."""
    found: list[Path] = []
    for path in sorted(src.rglob("*.xml")):
        if path.stat().st_size > 5 * 1024**2:
            continue
        try:
            if ET.parse(path).getroot().tag == "annotation":
                found.append(path)
        except (ET.ParseError, OSError):
            continue
    return found


def _attach_voc(items: list[_Item], xml_files: list[Path], src: Path) -> list[str]:
    """Give each picture its boxes from VOC XML (by <filename> or file stem). Class names: those found, sorted."""
    by_name = {Path(it.rel).name: it for it in items}
    by_stem = {Path(it.rel).stem: it for it in items}
    parsed: list[tuple[_Item, int, int, list[tuple[str, float, float, float, float]]]] = []
    names: set[str] = set()
    for xml in xml_files:
        root = ET.parse(xml).getroot()
        wanted = (root.findtext("filename") or "").strip()
        item = by_name.get(wanted) or by_stem.get(xml.stem) or by_stem.get(Path(wanted).stem)
        if item is None:
            continue
        width, height = (int(float(root.findtext(f"size/{k}") or 0)) for k in ("width", "height"))
        if not (width and height):
            with Image.open(item.path) as im:
                width, height = im.size
        boxes: list[tuple[str, float, float, float, float]] = []
        for obj in root.findall("object"):
            name = (obj.findtext("name") or "").strip()
            box = obj.find("bndbox")
            if not name or box is None:
                continue
            try:
                x1, y1, x2, y2 = (float(box.findtext(k) or "nan") for k in ("xmin", "ymin", "xmax", "ymax"))
            except ValueError:
                raise ImportProblem(
                    f"{xml.relative_to(src).as_posix()}: a box has a value that is not a number."
                ) from None
            names.add(name)
            boxes.append((name, x1, y1, x2, y2))
        parsed.append((item, width, height, boxes))
    if not parsed:
        raise ImportProblem("The XML files could not be matched to any picture (matched by <filename> or file name).")
    ordered = sorted(names)
    index = {n: i for i, n in enumerate(ordered)}
    for item, width, height, boxes in parsed:
        item.labels = []
        for name, bx1, by1, bx2, by2 in boxes:
            x1, y1, x2, y2 = max(bx1, 0.0), max(by1, 0.0), min(bx2, float(width)), min(by2, float(height))
            if x2 > x1 and y2 > y1:
                cx, cy, w, h = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height, (x2 - x1) / width, (y2 - y1) / height
                item.labels.append([float(index[name]), cx, cy, w, h])
    return ordered


# --- sources ----------------------------------------------------------------------------------------------------------


def _read_sources_csv(src: Path) -> dict[str, str]:
    path = src / "sources.csv"
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].strip().lower() not in ("file", "filename", "image"):
                out[row[0].strip().replace("\\", "/")] = row[1].strip()
    return out


def _source_from_folder(rel: str) -> str | None:
    for part in Path(rel).parts[:-1]:
        tag = SOURCE_TAGS.get(part.lower().replace("_", "-").replace(" ", "-"))
        if tag:
            return tag
    return None


def _source_from_exif(img: Image.Image) -> str | None:
    exif = img.getexif()
    make, model = str(exif.get(0x010F, "")).strip(), str(exif.get(0x0110, "")).strip()
    if "imx708" in model.lower():  # the sensor in the Raspberry Pi Camera Module 3 (including the wide version)
        return "rpi-cam3-wide"
    return "mobile" if (make or model) else None


# --- the import -------------------------------------------------------------------------------------------------------


def _bucket(megapixels: float) -> str:
    for limit, label in RESOLUTION_BUCKETS:
        if megapixels < limit:
            return label
    return "over 12 MP"


def _list_images(src: Path) -> list[Path]:
    files = [
        p
        for p in sorted(src.rglob("*"))
        if p.is_file() and not any(part.startswith(("__MACOSX", ".")) for part in p.relative_to(src).parts)
    ]
    images = [p for p in files if p.suffix.lower() in IMAGE_EXTENSIONS]
    if not images:
        heic = any(p.suffix.lower() in HEIC_EXTENSIONS for p in files)
        hint = " HEIC photos are not supported yet: convert them to JPEG first." if heic else ""
        raise ImportProblem("No images were found (looked for .jpg, .jpeg, .png, .bmp and .webp)." + hint)
    return images


def _read_labels(src: Path, items: list[_Item]) -> tuple[str, list[str] | None]:
    """Attach labels to the items. Returns the detected format and the class names found next to them, if any."""
    coco = _find_coco_json(src)
    if coco:
        return "coco", _attach_coco(items, coco)
    has_txt = any(_yolo_label_path(src, item.path) is not None for item in items)
    voc = [] if has_txt else _voc_files(src)
    if voc:
        return "voc", _attach_voc(items, voc, src)
    for item in items:
        label = _yolo_label_path(src, item.path)
        if label is not None:
            where = label.relative_to(src).as_posix()
            item.labels = _parse_yolo_label(label.read_text(encoding="utf-8", errors="replace"), where)
    return "yolo", _read_yaml_names(src)


def _load_image(item: _Item, csv_sources: dict[str, str]) -> tuple[Image.Image, bool, bytes | None]:
    """Open, rotate upright, convert to RGB; set the item's size, hash and capture source.

    Returns the picture, whether EXIF rotated it, and the original bytes if they can be stored as they are (an upright
    RGB JPEG within the size cap: re-encoding it would only add noise that shifts the accuracy numbers).
    """
    raw = item.path.read_bytes()
    item.sha = hashlib.sha256(raw).hexdigest()
    try:
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            oriented = ImageOps.exif_transpose(opened)
            exif_source = _source_from_exif(opened)
            rotated = oriented.size != opened.size
            as_is = (
                opened.format == "JPEG"
                and opened.mode == "RGB"
                and opened.getexif().get(0x0112, 1) == 1
                and max(opened.size) <= MAX_SIDE
            )
            rgb = oriented.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ImportProblem(f"{item.rel} could not be read as an image ({type(exc).__name__}).") from None
    item.width, item.height = rgb.size
    item.source = csv_sources.get(item.rel) or _source_from_folder(item.rel) or exif_source or "other"
    return rgb, rotated, raw if as_is else None


def _encode(rgb: Image.Image, original: bytes | None) -> tuple[Image.Image, bytes]:
    if original is not None:
        return rgb, original
    if max(rgb.size) > MAX_SIDE:
        scale = MAX_SIDE / max(rgb.size)
        rgb = rgb.resize((round(rgb.width * scale), round(rgb.height * scale)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=JPEG_QUALITY)
    return rgb, buf.getvalue()


@dataclass
class _Tally:
    num_classes: int
    class_counts: list[int] = field(default_factory=list)
    per_source: dict[str, dict[str, Any]] = field(default_factory=dict)
    sizes: Counter[tuple[int, int]] = field(default_factory=Counter)
    buckets: Counter[str] = field(default_factory=Counter)
    rotated: int = 0

    def __post_init__(self) -> None:
        self.class_counts = [0] * self.num_classes

    def add(self, item: _Item, rotated: bool) -> None:
        self.rotated += rotated
        self.sizes[(item.width, item.height)] += 1
        self.buckets[_bucket(item.width * item.height / 1e6)] += 1
        s = self.per_source.setdefault(
            item.source, {"images": 0, "labelled": 0, "instances": 0, "class_counts": [0] * self.num_classes}
        )
        s["images"] += 1
        if item.labels is not None:
            s["labelled"] += 1
            s["instances"] += len(item.labels)
            for row in item.labels:
                s["class_counts"][int(row[0])] += 1
                self.class_counts[int(row[0])] += 1


def _warnings(items: list[_Item], tally: _Tally) -> list[str]:
    out: list[str] = []
    if tally.rotated:
        out.append(
            f"{tally.rotated} image(s) carry an EXIF rotation and were rotated upright; "
            "labels are assumed to be drawn on the upright image."
        )
    labelled = sum(1 for it in items if it.labels is not None)
    if labelled == 0:
        out.append("No labels were found: this dataset supports speed runs only (accuracy shows n/a).")
    elif labelled < len(items):
        out.append(
            f"{len(items) - labelled} of {len(items)} images have no label file; accuracy uses the labelled ones."
        )
    return out


def import_directory(
    src: Path,
    out_zip: Path,
    *,
    names_hint: list[str] | None = None,
    progress: Callable[[float, str], None] | None = None,
) -> ImportResult:
    """Read ``src`` and write the normalised zip to ``out_zip``. Raises ``ImportProblem`` with a readable reason."""
    report = progress or (lambda _f, _m: None)
    items = [_Item(path=p, rel=p.relative_to(src).as_posix()) for p in _list_images(src)]
    fmt, found_names = _read_labels(src, items)
    max_class = max((int(r[0]) for it in items for r in (it.labels or [])), default=-1)
    generic = found_names is None and not names_hint
    names = found_names or (list(names_hint) if names_hint else [f"class_{i}" for i in range(max_class + 1)])
    if max_class >= len(names):
        raise ImportProblem(
            f"A label uses class {max_class}, but only {len(names)} class names are known. "
            "Add a data.yaml with the names, or check the label files."
        )

    csv_sources = _read_sources_csv(src)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    tally, manifest_images = _Tally(len(names)), []
    try:
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_STORED) as z:
            for n, item in enumerate(items):
                report(n / len(items), f"Preparing image {n + 1} of {len(items)}")
                rgb, rotated, original = _load_image(item, csv_sources)
                tally.add(item, rotated)
                rgb, jpeg = _encode(rgb, original)
                entry = f"images/{n:06d}.jpg"
                z.writestr(zipfile.ZipInfo(entry, date_time=FIXED_TIME), jpeg)
                manifest_images.append(
                    {
                        "file": entry,
                        "original": item.rel,
                        "original_sha256": item.sha,
                        "width": rgb.width,
                        "height": rgb.height,
                        "original_width": item.width,
                        "original_height": item.height,
                        "source": item.source,
                        "labels": item.labels,
                    }
                )
            lines = "".join(
                f"{it.rel}\0{it.sha}\0{_label_hash(it.labels)}\n" for it in sorted(items, key=lambda i: i.rel)
            )
            dataset_hash = hashlib.sha256(lines.encode()).hexdigest()
            manifest = {"version": 1, "format": fmt, "names": names, "dataset_hash": dataset_hash}
            manifest["images"] = manifest_images
            z.writestr(zipfile.ZipInfo("data.json", date_time=FIXED_TIME), json.dumps(manifest, separators=(",", ":")))
    except BaseException:
        out_zip.unlink(missing_ok=True)
        raise
    report(1.0, "Done")
    return ImportResult(
        format=fmt,
        names=names,
        names_generic=generic,
        image_count=len(items),
        labelled_count=sum(1 for it in items if it.labels is not None),
        instance_count=sum(len(it.labels or []) for it in items),
        dataset_hash=dataset_hash,
        size_bytes=out_zip.stat().st_size,
        stats={
            "class_counts": tally.class_counts,
            "sources": tally.per_source,
            "resolution": {
                "buckets": dict(tally.buckets),
                "sizes": [{"width": w, "height": h, "count": c} for (w, h), c in tally.sizes.most_common(8)],
            },
            "warnings": _warnings(items, tally),
        },
    )


# --- calibration subset -----------------------------------------------------------------------------------------------


def choose_calibration(images: list[dict[str, Any]], count: int = DEFAULT_CALIBRATION, seed: int = 0) -> dict[str, Any]:
    """A seeded sample for quantization calibration that mixes capture sources, recording exactly which files."""
    if len(images) < MIN_CALIBRATION:
        raise ImportProblem(f"Calibration needs at least {MIN_CALIBRATION} images and this dataset has {len(images)}.")
    count = max(MIN_CALIBRATION, min(count, len(images)))
    rng = random.Random(seed)
    groups: dict[str, list[str]] = {}
    for im in images:
        groups.setdefault(im["source"], []).append(im["original"])
    for files in groups.values():
        rng.shuffle(files)
    order = sorted(groups)  # a fixed order, so the same seed always gives the same list
    chosen: list[str] = []
    while len(chosen) < count:
        for source in order:
            if groups[source] and len(chosen) < count:
                chosen.append(groups[source].pop())
    return {"seed": seed, "count": len(chosen), "files": sorted(chosen)}


def read_manifest(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as z:
        data: dict[str, Any] = json.loads(z.read("data.json"))
    return data


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(name: str) -> str:
    return _SAFE.sub("_", name).strip("._") or "dataset"
