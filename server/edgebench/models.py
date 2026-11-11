"""Database tables. Phase 1 creates the tables later phases fill; each phase adds its columns in a new migration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    """Timezone-aware UTC. SQLModel's datetime column refuses naive values; SQLite stores them as UTC."""
    return datetime.now(UTC)


class Artifact(SQLModel, table=True):
    __tablename__ = "artifacts"

    sha256: str = Field(primary_key=True, max_length=64)
    kind: str
    size: int
    created_at: datetime = Field(default_factory=utcnow)
    source_job: int | None = Field(default=None, foreign_key="jobs.id")


class MlModel(SQLModel, table=True):
    __tablename__ = "models"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    artifact_sha256: str | None = Field(default=None, foreign_key="artifacts.sha256", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    filename: str = ""
    size_bytes: int = 0
    # inspecting -> ready; or converter_missing (no converter environment: retry); or rejected (not a usable model)
    status: str = "inspecting"
    error: str | None = None
    # The model card, read by converter/inspect_pt.py.
    task: str | None = None
    imgsz: int | None = None
    parameters: int | None = None
    gflops: float | None = None
    class_names: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    archived: bool = False


class Variant(SQLModel, table=True):
    """One cell of the conversion matrix: a model in one format and precision."""

    __tablename__ = "variants"
    __table_args__ = (UniqueConstraint("model_id", "op", "imgsz", "settings_key", name="uq_variants_cell"),)

    id: int | None = Field(default=None, primary_key=True)
    model_id: int = Field(foreign_key="models.id", index=True)
    op: str  # onnx_fp32, onnx_fp16, torchscript, openvino_fp32, ...
    format: str  # ONNX, OpenVINO, ncnn, TorchScript
    precision: str  # FP32, FP16
    imgsz: int
    settings: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    settings_key: str = ""  # settings as sorted JSON, so the unique cell key can include them
    cache_key: str = Field(default="", index=True)  # ADR 0002
    # pending, converting, ready, failed, unavailable (a package is missing), cancelled
    state: str = "pending"
    mismatch: bool = False  # converted, but its output differs from PyTorch's by more than the tolerance
    cached: bool = False  # reused from an earlier identical conversion
    artifact_sha256: str | None = Field(default=None, foreign_key="artifacts.sha256", index=True)
    main_file: str | None = None
    size_bytes: int | None = None
    seconds: float | None = None
    verify: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: str | None = None
    log: str | None = None
    job_id: int | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Dataset(SQLModel, table=True):
    """A named collection of pictures with a history, like a repository: every change is a ``DatasetVersion``."""

    __tablename__ = "datasets"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    description: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    head_version_id: int | None = None  # the newest version that finished building
    archived: bool = False


class DatasetVersion(SQLModel, table=True):
    """One snapshot of a dataset. ``manifest`` lists the files (path, SHA-256, size) it consists of; the files are
    shared between versions in the artifact store. ``artifact_sha256`` is the normalised copy the agents read."""

    __tablename__ = "dataset_versions"
    __table_args__ = (UniqueConstraint("dataset_id", "number", name="uq_dataset_version_number"),)

    id: int | None = Field(default=None, primary_key=True)
    dataset_id: int = Field(foreign_key="datasets.id", index=True)
    number: int
    message: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    parent_id: int | None = None  # the head this version was made from
    status: str = "building"  # building -> ready, or failed
    error: str | None = None
    manifest: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    changes: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    format: str | None = None  # yolo, coco or voc, whatever the importer detected
    image_count: int = 0
    labelled_count: int = 0
    instance_count: int = 0
    class_names: list[str] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    names_generic: bool = False  # the folder had no class names, so these are placeholders
    dataset_hash: str | None = Field(default=None, index=True)  # over (name, original bytes hash, label hash), sorted
    artifact_sha256: str | None = Field(default=None, foreign_key="artifacts.sha256", index=True)
    size_bytes: int = 0
    stats: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    calibration: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    source_path: str | None = None  # set when the files were read from a folder on this machine


class Device(SQLModel, table=True):
    __tablename__ = "devices"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    token_hash: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime | None = None
    # What the person said they were setting up (from the browser's hint); the real type comes from the fingerprint.
    expected_kind: str | None = None
    kind: str | None = None  # pc or pi, from the agent's fingerprint
    enroll_hash: str | None = Field(default=None, index=True)  # one-time token, cleared when used
    enroll_expires_at: datetime | None = None
    fingerprint: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    agent_version: str | None = None
    revoked: bool = False


class Experiment(SQLModel, table=True):
    """A named group of runs that share a dataset version, a device and settings (one model variant per run)."""

    __tablename__ = "experiments"

    id: int | None = Field(default=None, primary_key=True)
    name: str
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    dataset_id: int | None = Field(default=None, foreign_key="datasets.id")
    dataset_version_id: int | None = Field(default=None, foreign_key="dataset_versions.id")
    device_id: int | None = Field(default=None, foreign_key="devices.id")
    params: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    # What was asked for (the items and the sweep), kept so a cancelled sweep can be resumed without repeating runs.
    plan: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))


class Run(SQLModel, table=True):
    """One variant (or the ``.pt`` baseline) measured on one dataset by one device (Phase 3)."""

    __tablename__ = "runs"

    id: int | None = Field(default=None, primary_key=True)
    experiment_id: int | None = Field(default=None, foreign_key="experiments.id", index=True)
    device_id: int | None = Field(default=None, foreign_key="devices.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    model_id: int | None = Field(default=None, foreign_key="models.id", index=True)
    variant_id: int | None = Field(default=None, foreign_key="variants.id")  # None = the .pt baseline
    dataset_id: int | None = Field(default=None, foreign_key="datasets.id", index=True)
    dataset_version_id: int | None = Field(default=None, foreign_key="dataset_versions.id", index=True)
    job_id: int | None = Field(default=None, index=True)
    params: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    # None while the job is queued or running (its state says which); then done, failed or unavailable.
    outcome: str | None = None
    error: str | None = None
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    started_at: datetime | None = None
    finished_at: datetime | None = None


class Job(SQLModel, table=True):
    """A unit of work. States: queued, claimed, running, done, failed, cancelled, lost (ADR 0001)."""

    __tablename__ = "jobs"
    # Serves the claim query (state = 'queued' ordered by priority, id) and the per-state counts on /api/health.
    __table_args__ = (Index("ix_jobs_claim", "state", "priority", "id"),)

    id: int | None = Field(default=None, primary_key=True)
    type: str = Field(index=True)
    params: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    state: str = "queued"
    priority: int = 0
    attempts: int = 0
    max_attempts: int = 3
    cancel_requested: bool = False
    device_id: int | None = Field(default=None, index=True)  # set for jobs that an agent on that device must run
    worker: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    claimed_at: datetime | None = None
    heartbeat_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: str | None = None
