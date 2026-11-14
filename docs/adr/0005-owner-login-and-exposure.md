# ADR 0005: One owner password guards the site before it leaves this machine

Status: accepted (Phase 5, 2026-11-12). Login is built and tested on the PC. Nothing here has been tested over a real LAN, Tailscale or the
internet, and no Raspberry Pi has connected yet.

## Context
Until now the server listened on `127.0.0.1` with no login, which is safe only because nobody else can reach it. Phase 5 puts a Pi on
another network, and the owner wants the whole site (not only the agent door) reachable there, later on the internet. Anyone who could
reach an open site could upload a model file, start conversions, read datasets and delete everything.

## Decision
- **One owner, one password**, set on the server with `python -m edgebench set-password` (at least 12 characters, scrypt N=2^15 r=8 p=1,
  stored in `data/owner.json`). There is no sign-up page, so nobody can claim an exposed server first.
- **Off until a password exists** (so local development and every earlier test behave as before). Once `data/owner.json` exists, every
  `/api/*` and `/ws/*` request needs the `eb_session` cookie; the check is a pure ASGI middleware (`auth.AuthGate`) so WebSockets are covered.
  `/api/auth/*` is open (status, login, logout). `/agent/*` keeps its own device tokens (ADR 0003). The built web pages are public: they hold
  no data, and the sign-in page is one of them.
- **Cookie**: random 256-bit value, only its hash is kept; `HttpOnly`, `SameSite=Strict`, `Secure` when the request is https or
  `EDGEBENCH_SECURE_COOKIE=true` (for a tunnel that terminates TLS), seven days. Login and logout also pass the same-origin guard.
- **Guessing is throttled**: five wrong passwords per address per five minutes (then 429 with `Retry-After`, even for the right password);
  ten wrong enrolment tokens per address per five minutes.
- **The server refuses to listen beyond this machine without a password** (`auth.check_bind`, in `python -m edgebench` and in the app's start-up).
  The names to answer to must also be listed in `EDGEBENCH_ALLOWED_HOSTS` (DNS-rebinding guard stays on).
- **Network modes**: the same-network address, and Tailscale (or a tunnel). The agent only makes outbound calls, as before.

## Alternatives rejected
- Expose only `/agent/*`: safest, but the owner wants the Pi's browser to open the site and, later, a deployed site.
- Rely on Tailscale alone: no login, so a deployed site would be open; kept as an extra layer, not the only one.
- Sessions in the database: survives restarts but needs a migration; sessions are in memory for now.

## Consequences and limits
- A server restart signs the owner out. The password change signs everyone out.
- The throttle counts by the peer address; behind a reverse proxy or tunnel that is the proxy's address, so everyone shares one allowance.
- No second factor, no password reset by e-mail (reset = run `set-password` on the server), no rate limit on other routes.
- Plain `http://` on a LAN sends the password and cookie unencrypted. Use Tailscale (encrypted) or an https tunnel off the home network.
- Not yet reviewed by someone else.
