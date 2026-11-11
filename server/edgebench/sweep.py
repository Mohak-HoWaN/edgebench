"""Expanding a sweep into runs: every combination of model variant, thread count, pinned CPUs and input size, minus the
combinations that cannot be run (each with its reason), and an estimate of how long the rest will take.

Pure functions: the API looks up the variants and the device and passes plain values in, so each rule is tested
on its own.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from dataclasses import dataclass

MAX_RUNS = 400  # a sweep larger than this is almost certainly a mistake, and would queue for days
LOAD_SECONDS = 3.0  # starting the process, loading the model and the first (slow) inference
GUESS_MS = 40.0  # one inference when nothing on this device has been measured yet
DECODE_FACTOR = 1.4  # the accuracy pass also reads, decodes and scores every picture


@dataclass(frozen=True)
class Subject:
    """One thing the person picked: a conversion (or the ``.pt`` baseline) and the sizes it exists at."""

    model_id: int
    variant_id: int | None  # None: the .pt baseline
    label: str
    native_imgsz: int
    sizes: dict[int, int]  # input size -> id of this same conversion at that size (only finished ones)


@dataclass(frozen=True)
class Config:
    subject: Subject
    variant_id: int | None
    threads: int
    cpu_list: tuple[int, ...] | None
    imgsz: int

    @property
    def key(self) -> tuple[int | None, int, tuple[int, ...]]:
        """What makes two runs the same measurement (the size is part of the variant)."""
        return (self.variant_id, self.threads, self.cpu_list or ())

    @property
    def label(self) -> str:
        size = "" if self.imgsz == self.subject.native_imgsz else f" at {self.imgsz} px"
        return f"{self.subject.label}{size}"


@dataclass(frozen=True)
class Pruned:
    label: str
    threads: int
    cpu_list: tuple[int, ...] | None
    imgsz: int
    reason: str


def expand(
    subjects: Sequence[Subject],
    threads: Sequence[int],
    cpu_sets: Sequence[Sequence[int] | None],
    sizes: Sequence[int | None],
    logical_cores: int | None,
) -> tuple[list[Config], list[Pruned]]:
    """The runs of the sweep and the combinations left out. An empty axis means "as the base settings say" (None)."""
    kept: list[Config] = []
    pruned: list[Pruned] = []
    seen: set[tuple[int | None, int, tuple[int, ...]]] = set()
    for subject, nthreads, cpus, size in itertools.product(subjects, threads, cpu_sets or [None], sizes or [None]):
        imgsz = size or subject.native_imgsz
        pinned = tuple(sorted(set(cpus))) if cpus else None
        name = subject.label if imgsz == subject.native_imgsz else f"{subject.label} at {imgsz} px"

        def skip(
            reason: str, name: str = name, n: int = nthreads, p: tuple[int, ...] | None = pinned, s: int = imgsz
        ) -> None:
            pruned.append(Pruned(name, n, p, s, reason))

        if pinned and logical_cores is not None and (pinned[0] < 0 or pinned[-1] >= logical_cores):
            skip(f"the device has CPUs 0 to {logical_cores - 1}, and the list names one beyond that")
            continue
        room = len(pinned) if pinned else logical_cores
        if room is not None and nthreads > room:
            where = f"the {len(pinned)} pinned CPUs" if pinned else f"the device's {logical_cores} CPUs"
            skip(f"{nthreads} threads do not fit on {where}")
            continue
        if subject.variant_id is None and imgsz != subject.native_imgsz:
            skip("the .pt baseline is run at the model's own input size")
            continue
        variant_id = subject.variant_id if imgsz == subject.native_imgsz else subject.sizes.get(imgsz)
        if imgsz != subject.native_imgsz and variant_id is None:
            skip(f"there is no finished conversion at {imgsz} px; convert it on the Models page first")
            continue
        config = Config(subject, variant_id, nthreads, pinned, imgsz)
        if config.key in seen:
            continue  # the same measurement named twice (for example two CPU sets that are the same list)
        seen.add(config.key)
        kept.append(config)
    return kept, pruned


def seconds_for_run(
    images: int, ms_per_inference: float, warmup: int, iterations: int, repeats: int, *, accuracy: bool
) -> float:
    """A rough duration of one run: load, one pass over the pictures for accuracy, and the timed repeats."""
    one = ms_per_inference / 1000.0
    timed = repeats * (warmup + iterations) * one
    return LOAD_SECONDS + (images * one * DECODE_FACTOR if accuracy else 0.0) + timed


def median(values: Sequence[float]) -> float | None:
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
