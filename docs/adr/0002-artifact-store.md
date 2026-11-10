# ADR 0002: Content-addressed artifact store with a toolchain-aware cache key

Status: accepted (Phase 0, 2026-11-09)

## Context
Variants are single files (`.onnx`, `.engine`) or bundles (OpenVINO `.xml` + `.bin`, ncnn `.param` + `.bin`). The same converter can
produce different output after a library update (Phase 0 showed two ONNX FP16 converters giving one working and one broken file), and a
TensorRT engine is valid only for one GPU and one TensorRT version.

## Decision
- Files live at `data/artifacts/<sha256[:2]>/<sha256>`. A bundle is stored as its member files plus a small manifest; the bundle's
  identity is the SHA-256 of the manifest (member names and hashes, sorted).
- The database table `artifacts` holds `sha256`, `kind`, `size`, `created_at`, `source_job`. Writing is: write to a temp name in the same
  folder, fsync, atomic rename. A crash leaves no half-written artifact.
- **Conversion cache key** = SHA-256 of (source model sha256, format, precision, image size, converter settings as sorted JSON,
  converter name and version, and for device-built formats the device fingerprint). A hit returns the existing artifact and the UI shows
  "cached".
- Agents cache downloads by artifact sha256 under their own data folder and verify the hash after download.
- Deleting is a soft archive; garbage collection (Settings, with a dry-run list) removes artifacts no run or variant references.

## Consequences
- The same model uploaded twice is stored once.
- A changed converter version is a cache miss, which is deliberate.
- Moving the store to another machine is a plain copy.
