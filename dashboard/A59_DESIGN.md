# A59: Telegram-controlled, on-demand dashboard (design, isolated implementation, tests)

**Status:** prototype only. Not deployed, not wired into the live bot, no database role provisioned, no port or
tunnel opened. Development used synthetic data and mock adapters only.

## 1. How it works
- **Bot side (prototype `telegram_control.py`):** three owner-only buttons, Open, Close and Status.
  - Owner = the existing `TELEGRAM_CHAT_ID` value, parsed as a positive number. It must equal the sender's user id, in a private chat with that same id.
  - Non-owners get no reply; one log line records the attempt, without ids.
- **Bot → dashboard:** a unix socket (mode 0600) carrying HMAC-SHA256-signed `{op, ts, nonce}`.
  - ±30 s clock skew allowed; nonce replay rejected.
  - Only `open`, `close` and `status` exist. There is no shell, Docker, database-admin or trading capability.
- **Open:**
  - bumps the generation, which revokes every earlier link and session;
  - issues one link: 256-bit random token, stored only as sha256, single use, valid 60 s;
  - binds the HTTPS listener, which does not exist at any other time.
- **Login:**
  - atomic redemption (`UPDATE … WHERE used=0 AND gen=current AND expires>now`; exactly one winner);
  - the response sets the `__Host-a59` cookie: Secure, HttpOnly, SameSite=Strict, Path=/;
  - the token leaves the address bar through a 303 to `/`, with `Referrer-Policy: no-referrer`.
- **Session:**
  - ends at the window end, at most 15 min after Open; never extended;
  - the data API requires a custom header and a same-origin `Origin`;
  - Close in the web page also requires the per-session CSRF token and an exact `Origin`.
- **Closing:**
  - happens on Close (Telegram or web), on window or link expiry (1 s watchdog), and on service start;
  - order: stop the listener first, then revoke, then verify both;
  - a failure is returned and shown as "🚨 فشل الإغلاق" (a security incident), never hidden;
  - an undelivered Telegram link is revoked immediately.
- **Logs:** method, path without the query string, status. Tokens and cookies never reach a log line.
- **Data:**
  - `MockAdapter` (synthetic) in development;
  - `PostgresAdapter` reads only `dashboard.<view>` from the R-5 allowlist, in a read-only transaction with timeouts;
  - status levels are computed on the server, so stale, missing or erroring data is never shown green.

## 2. Access architectures

| | A: private VPN (WireGuard) | B: temporary internet tunnel | C: persistent minimal gateway |
|---|---|---|---|
| Attack surface while closed | **none on HTTP** (listener absent); one WireGuard UDP port that ignores unauthenticated packets | none while closed; **public HTTPS** while open | **public gateway always on** |
| Authentication | device key (VPN) **plus** Telegram-gated single-use link and session | link and session only; anyone who obtains a live link within 60 s can try | gateway login plus link; gateway itself always attackable |
| Revocation | local, immediate (listener stop + generation bump) | must also stop the tunnel; depends on the provider | local, but the gateway stays up |
| External dependency | none (self-hosted WireGuard); Telegram only to open | tunnel provider (DNS, TLS, availability) | public DNS and TLS; certificates |
| Mobile usability | needs the WireGuard app with one profile (QR); then one tap | best (plain HTTPS link) | best |
| Cost | free | free tier or paid; third party sees metadata | free; ongoing hardening |
| Shared host fit | adds one UDP port; no change to Caddy/xsch/wishlist | a new outbound tunnel process | touches the public edge shared with other apps |
| Telegram unavailable | cannot open (fail-closed); expiry still closes | same | same |
| Process when closed | **listener stopped** (port not bound); controller only on a 0600 socket | same, plus the tunnel stopped | gateway running; data disabled |

**Recommendation: A.**
- **Why:** with two independent factors (VPN device key plus Telegram-gated link), the dashboard is never reachable from the public internet and the HTTP listener only exists during a session. Revocation does not depend on a third party.
- **Trade-off:** one-time VPN setup on the phone.
- **Fallback:** B is acceptable only if VPN setup is rejected, and needs its own approval.
- **Not recommended:** C, because it is permanently public on a host shared with other applications.

## 3. Threat model (assets, boundaries, attacks, mitigations)
- **Assets:** operational state (no outcomes); the Telegram bot token; the control key; session cookies; the shared host.
- **Trust boundaries:** phone browser ↔ (VPN) ↔ dashboard listener; Telegram ↔ bot; bot ↔ control socket; dashboard ↔ PostgreSQL (`tsb_dashboard_ro`, views only).

| Attack | Mitigation (tested) |
|---|---|
| Stranger or group chat sends Open | owner gate on user id plus private chat id; silent ignore (T01, T02) |
| Link leak or replay | 60 s TTL, single use, atomic; superseded by the next Open (T03, T04, T09) |
| Concurrent redemption race | `BEGIN IMMEDIATE` conditional update; exactly 1 of 12 succeeds (T03b) |
| Stolen cookie after close or expiry | server-side generation revocation; listener gone (T05, T06, T10, T11) |
| Restart restores access | start bumps the generation (T08) |
| CSRF or cross-origin reads | SameSite=Strict, custom header, Origin check, CSRF token; CSP `default-src 'none'`, frame-ancestors none (T13) |
| Token in logs or Referer | scrubbed access log, 303, no-referrer, no-store (T12) |
| Control socket abuse | 0600, HMAC, nonce and skew, 3-op allowlist; no shell or Docker code (T14, T14b) |
| XSS from data | `textContent` only, no inline script, strict CSP (T17) |
| Holdout or research exposure | view allowlist only; no outcome fields; R-5 role cannot read `public` (T16, T16b, INT-03) |
| Dashboard breaks trading | no trading module imports it; read-only role; source failure is contained (T15, T15b) |

## 4. Proposed future deployment (not executed; needs approvals)
1. **Container:** a separate `a59_dashboard` container (non-root, read-only rootfs, `cap_drop: ALL`, memory and CPU limits, no Docker socket).
   - The HTTPS listener binds only to the WireGuard interface address.
   - The control socket is a shared volume with the bot only.
2. **WireGuard:**
   - `wg0` on the host, with one peer (the owner's phone) and one UDP port opened in the firewall;
   - TLS from a private CA, or a certificate for a private name.
3. **Database:** R-5 Stage 1 roles, plus `dashboard_v1.sql`, plus LOGIN for `tsb_dashboard_ro`, in a dedicated credential file.
4. **Bot integration:** add the three buttons to the live telegram service. This is a code change plus a recreate, Class B, separately approved.
5. **Rollback:** stop the container (the port is already closed when idle); remove the buttons; remove the WireGuard peer; `roles_v3_rollback.sql` covers the database side.
6. **Cost:** €0 (self-hosted). Operational: WireGuard key management, certificate renewal.

## 5. Tests and limitations
- **Results:** 27/27 pass (`evidence/test_run.txt`). The R-5 integration also passes (`evidence/r5_integration.txt`): the real adapter as `tsb_dashboard_ro` reads the 6 views, is not a superuser, is denied the `public` tables, and is denied writes through views.
- **Not tested:**
  - real phone browsers: RTL and mobile were checked from the markup and CSS only;
  - the live Telegram API and the python-telegram-bot callback wiring: handlers were exercised with fake updates;
  - WireGuard and certificates;
  - load.
- **Sessions:** a single active session by design. A second Open supersedes, and revokes, the first.
