"""Can this converter read this model correctly, and were a model's variants built by a converter that still matches?

A converter that is too old for a model does not refuse it: Ultralytics 8.3 loads a YOLO26 file without an error and
decodes it wrongly, and the PyTorch-versus-converted check passes because both sides share the same wrong reading.
So the only evidence is the file's own record of the library that made it (docs/brief-model-compatibility-guards.md).
"""

from __future__ import annotations

import re
from typing import Any

# Families that need a newer Ultralytics than the version stamp alone might suggest.
# shortcut: only YOLO26 is known; add a family here when one appears, the version stamp covers the rest.
FAMILY_MIN = {"26": (8, 4)}
CHECKED = (
    "ultralytics",
    "torch",
    "onnx",
    "onnxruntime",
    "openvino",
    "ncnn",
)  # libraries whose change makes a variant stale


def parse(version: str | None) -> tuple[int, int] | None:
    m = re.match(r"(\d+)\.(\d+)", version or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def architecture(train_model: str | None) -> str | None:
    """``ul://ultralytics/yolo26/yolo26n`` and ``yolo11n.pt`` give ``yolo26n`` and ``yolo11n``."""
    if not train_model:
        return None
    name = re.split(r"[/\\]", str(train_model))[-1]
    return re.sub(r"\.(pt|yaml)$", "", name) or None


def check(card: dict[str, Any], versions: dict[str, str], python: str | None) -> dict[str, Any]:
    """The compatibility record stored with the model: ``ok``, and when not, the plain-words ``message``."""
    trained = card.get("trained_with")
    arch = architecture(card.get("train_model"))
    converter = versions.get("ultralytics")
    needed: tuple[int, int] | None = parse(trained)
    family = re.search(r"yolo(?:v)?(\d+)", arch or "")
    if family and family.group(1) in FAMILY_MIN:
        needed = max(needed or (0, 0), FAMILY_MIN[family.group(1)])
    have = parse(converter)
    record: dict[str, Any] = {
        "trained_with": trained,
        "architecture": arch,
        "converter": converter,
        "ok": True,
        "message": None,
    }
    if needed is not None and have is not None and have < needed:
        want = f"{needed[0]}.{needed[1]}"
        record["ok"] = False
        label = f"{trained or want} ({arch})" if arch else (trained or want)
        record["message"] = (
            f"This model was trained with Ultralytics {label}, but this converter has {converter}, "
            "which cannot read it correctly. Nothing is wrong with your model. "
            f"Install Ultralytics {want} or newer in the converter environment "
            f'({python or "its Python"} -m pip install "ultralytics>={want}", with the constraints file '
            "from converter/README.md), then press Check again."
        )
    return record


def stale_reason(toolchain: dict[str, str] | None, versions: dict[str, str]) -> str | None:
    """Why a finished variant no longer matches the converter, or None when it does."""
    if not versions:
        return None  # no converter to compare with (not set up): nothing to say
    if toolchain is None:
        return "Built before converter versions were recorded. Rebuild it to be sure it matches the current converter."
    changed = [
        f"{name} {toolchain[name]} (now {versions[name]})"
        for name in CHECKED
        if name in toolchain and name in versions and toolchain[name] != versions[name]
    ]
    return f"Built by an older converter: {', '.join(changed)}. Rebuild it." if changed else None


def older_than_model(ultralytics: str | None, trained_with: str | None, who: str) -> str | None:
    """The failure this module exists for: ``who`` runs an Ultralytics older than the one that trained the model."""
    built, trained = parse(ultralytics), parse(trained_with)
    if built is None or trained is None or built >= trained:
        return None
    return (
        f"{who} Ultralytics {ultralytics}, but the model was trained with {trained_with}: "
        "an older library can read a newer model wrongly and still report it as fine."
    )
