---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# The operator cannot sign in

| | |
|---|---|
| **Severity** | SEV-3 |
| **Impact** | The operator cannot use the web app. The CLI still works. |
| **Signals** | `429 too_many_attempts`; sign-in appears to succeed but the next page asks again (cookie not kept); `login_throttled` for every client at once |
| **Related** | [API conventions](../../api/api-conventions.md#authentication), [R-13](../../tech-debt-and-risks.md#r-13--p2--security-session-and-login-hardening) |

On the VM, set up the usual alias first:

```bash
cd /opt/outbound/current && export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'
```

## 1. Confirm

```bash
oc logs --since 1h api | grep -E '"login_(failed|throttled|succeeded)"' | tail
```

| Pattern | Cause |
|---|---|
| `login_throttled` after failures | 5 wrong passwords in 60 s from that address. Wait a minute |
| Every login throttled together, with the same `client_ip` | The proxy does not send `X-Forwarded-For`, so every request looks like it comes from the proxy |
| Sign-in "works" but the session is lost | The site is not on HTTPS (the cookie is `Secure`), or the proxy does not forward to the app correctly |
| `bad_credentials` with the right password | `OPERATOR_PASSWORD_HASH` does not match: regenerate it |

## 2. Contain

—

## 3. Fix

- Configure the proxy to set `X-Forwarded-For` (`deploy/nginx.conf.example`) and serve HTTPS.
- To reset the password: `uv run outbound auth hash-password` on a trusted machine, put the result in Doppler (`OPERATOR_PASSWORD_HASH`), and restart `api`. A hash pasted into an env file must be in single quotes, because `$` is special.

## 4. Verify

Sign-in works; `login_succeeded` is logged with the real client address.

## 5. Follow up

—
