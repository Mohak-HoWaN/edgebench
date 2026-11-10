# ADR 0003: Agents poll over HTTP; the browser gets live updates over WebSocket

Status: accepted (Phase 0, 2026-11-09). Pi network behaviour is **not yet tested** and is re-checked in Phase 5.

## Context
The server runs on the PC. The Pi has its own internet (Wi-Fi, LAN or hotspot) and may be on another network; it may sit behind NAT. The
agent must stay light and must not disturb timing.

## Decision
Agents only make outbound requests:
- `POST /agent/enroll` with a one-time token returns a long-lived device token (stored hashed on the server, revocable).
- `POST /agent/claim` is a 25 s long poll; it returns a job or 204. `POST /agent/heartbeat` every 5 s carries the job id, agent version
  and a short status. No heartbeat for 30 s marks the device offline and its running job `lost` (ADR 0001).
- `GET /agent/artifacts/<sha256>` serves artifacts and datasets with `Range` support (resumable); the agent verifies the hash.
- `POST /agent/telemetry` takes batches (the sampler runs in a separate process at 5 Hz; the agent uploads every 2 s) and
  `POST /agent/result` uploads run results and logs.
- Timestamps: the agent sends monotonic offsets from its job start; the server adds its own receive time. A Pi without a battery clock
  can have a wrong wall clock, so wall-clock time from agents is never trusted.
- Updates: the agent reports its version; when idle it may download the matching wheel from the server and restart itself.
- The browser connects to `/ws/events` for job progress, logs and live telemetry; it never talks to agents directly.
- Device type is **recorded from the agent's hardware fingerprint**, not from the browser. The "This device" panel only uses the browser's
  platform string to choose which install command to show (Phase 3 and 5).

## Alternatives rejected
- Agent WebSocket: nicer latency, but long-lived sockets are brittle through hotspots and tunnels and harder to resume.
- Server-initiated connections to agents: impossible behind NAT.

## Consequences
- Works unchanged for a Pi on the same network, or on another network through a private overlay such as Tailscale.
- Job pickup latency is at most the poll interval; irrelevant for long jobs.
- All agent traffic is plain HTTP on a trusted network unless the owner adds TLS or an overlay; tokens must therefore be short-lived on enrolment
  and the server must refuse LAN binding until a token exists (Phase 5 security review).
