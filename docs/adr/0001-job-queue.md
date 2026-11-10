# ADR 0001: Job queue is a SQLite table, not Redis

Status: accepted (Phase 0, 2026-11-09)

## Context
Conversions, benchmark runs and report builds are long jobs that must survive a server restart, be cancellable, and be retried. Redis is
not installed on the development PC and has no native Windows build; the owner runs the server on Windows.

## Decision
A `jobs` table in the existing SQLite database (WAL mode). A worker claims a job with one atomic statement
(`UPDATE jobs SET state='claimed', worker=?, claimed_at=? WHERE id=(SELECT id FROM jobs WHERE state='queued' ORDER BY priority, id LIMIT 1) RETURNING *`).
Columns: `type`, `params` (JSON), `state` (queued, claimed, running, done, failed, cancelled, lost), `attempts`, `max_attempts`,
`cancel_requested`, `heartbeat_at`, `result`, `error`. Workers update `heartbeat_at` every 5 s. At start-up, and every 30 s, a job in
`claimed`/`running` whose heartbeat is older than 30 s returns to `queued` (or `lost` when attempts are exhausted). Cancel sets
`cancel_requested`; the worker checks it between steps and kills its subprocess.

Conversion and benchmark work always runs in a subprocess (Phase 0: a native crash in ncnn and a silent package replacement by Ultralytics
both happened), so the worker only supervises.

## Consequences
- One server host, one SQLite writer. Enough for a single developer tool; revisit if jobs ever run on several server hosts.
- No extra service to install; tests use a temporary database.
- Throughput is irrelevant here (tens of jobs, each seconds to hours).
