---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Sending targets by webhook

This guide is for another system (a CRM, a form, a script) that wants to add target companies to Outbound. The endpoint needs no login: each request is signed with a secret you share with the operator. Both examples below were checked against the server's own `verify` function.

## 1. Get the secret

The operator sets `INTAKE_WEBHOOK_SECRET` (Doppler in production, `.env` locally) to a long random value, for example from `openssl rand -hex 32`. They give it to you over a private channel. Until it is set, the endpoint answers `503 webhook_disabled`.

## 2. Build the body

`POST https://<outbound host>/api/intake/webhook`, with a JSON object of at most 1 MB:

```json
{
  "event_id": "crm-2026-10-21-0042",
  "targets": [
    { "company": "Acme Energy Ltd", "website": "example.com", "country": "GB",
      "person": "Jane Doe", "title": "Head of Trading", "email": "jane@example.com",
      "notes": "Met at the conference", "priority": 2 }
  ]
}
```

| Field | Rules |
|---|---|
| `event_id` | **Required.** Your unique id for this delivery. A second request with the same id is answered `{"duplicate": true}` and creates nothing, so retries are safe |
| `targets` | 1 to 200 objects. If `targets` is absent, the body itself (minus `event_id`) is treated as one target |

**Target fields.** Header matching is loose and ignores case and punctuation, so `companyName`, `Company` and `organisation` all mean `company`. Unknown fields are kept with the row but ignored.

| Meaning | Accepted names (examples) |
|---|---|
| company | `company`, `company_name`, `organisation`, `account`, `name` |
| website | `website`, `domain`, `url`, `site` |
| email | `email`, `work_email`, `contact_email` |
| person | `person`, `contact`, `full_name`, `decision_maker` |
| title | `title`, `job_title`, `role`, `position` |
| linkedin | `linkedin`, `linkedin_url`, `profile` |
| country | `country`, `country_code`, `location` |
| notes | `notes`, `comments`, `context` |
| priority | `priority`, 1 (highest) to 9 |

Each target needs at least one anchor: a company name, a website, a work email, or a LinkedIn profile URL. A company given only by name is resolved with one web search. If the match is not certain, the row waits for the operator to confirm the website.

**Leads sent this way count as chosen by the operator.** They skip the campaign's fit gate, and the values you send are protected from being overwritten by research. The intake actor is `user:webhook`.

## 3. Sign it

The signature is an HMAC-SHA256, keyed with the secret, over the timestamp, a dot, and the **exact bytes of the body**. Send it in two headers:

| Header | Value |
|---|---|
| `X-Timestamp` | Unix time in seconds, as a string. Must be within ±300 seconds of the server's clock |
| `X-Signature` | `sha256=` followed by the lower-case hex digest |
| `Content-Type` | `application/json` |

Sign the bytes you send. Re-serialising the JSON after signing changes the bytes and breaks the signature.

**Shell (curl and openssl):**

```bash
SECRET='…'                                   # INTAKE_WEBHOOK_SECRET
BODY='{"event_id":"crm-42","targets":[{"website":"example.com"}]}'
TS=$(date +%s)
SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | sed 's/^.* //')
curl -sS https://outbound.example.com/api/intake/webhook \
  -H 'Content-Type: application/json' \
  -H "X-Timestamp: $TS" -H "X-Signature: sha256=$SIG" \
  --data-binary "$BODY"
```

**Python:**

```python
import hashlib, hmac, json, time, urllib.request

secret = "…"  # INTAKE_WEBHOOK_SECRET
body = json.dumps({
    "event_id": "crm-42",
    "targets": [{"company": "Acme Energy Ltd", "website": "example.com"}],
}).encode()
ts = str(int(time.time()))
sig = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()

request = urllib.request.Request(
    "https://outbound.example.com/api/intake/webhook",
    data=body,
    headers={"Content-Type": "application/json", "X-Timestamp": ts, "X-Signature": sig},
    method="POST",
)
with urllib.request.urlopen(request, timeout=30) as response:
    print(response.status, response.read().decode())
```

## 4. Read the answer

```json
{ "duplicate": false, "batch_id": "0193…",
  "rows": [ { "status": "accepted", "domain": "example.com", "reason": null } ] }
```

| Row `status` | Meaning |
|---|---|
| `accepted` | A new lead was created |
| `merged` | The domain was already a lead. Notes were added, and differing values were recorded beside the existing ones |
| `needs_confirmation` | The website for a company name was not certain; the operator will choose |
| `pending` | A name could not be looked up yet, for example because search is not configured |
| `rejected` | See `reason`: suppressed domain or address, free-mail address with no company, a platform domain, nothing to go on |

`{"duplicate": true}` means this `event_id` was already received.

## 5. Handle errors

Errors are [problem details](api-conventions.md#errors) with a stable `code`:

| Status | `code` | What to do |
|---|---|---|
| 401 | `bad_signature` | Check the secret, the headers, and that you signed the exact bytes sent. Do not retry unchanged |
| 401 | `stale_timestamp` | Your clock is more than 5 minutes off, or you retried an old request: re-sign with the current time |
| 413 | `body_too_large` | Split into smaller batches (≤ 1 MB, ≤ 200 targets) |
| 422 | `bad_json` | The body is not a JSON object |
| 422 | `missing_event_id` | Add an `event_id` |
| 422 | `bad_targets` | Send 1 to 200 target objects |
| 503 | `webhook_disabled` | The operator has not set the secret |
| 500 | `internal_error` | Retry later with the **same** `event_id` (safe: duplicates are ignored); quote the reference to the operator |

The endpoint has no rate limit of its own ([R-13](../tech-debt-and-risks.md#r-13--p2--security-session-and-login-hardening)). Send batches, not one request per target, and retry with back-off.

## Reference

- **Code:**
  - `outbound/api/routers/webhook.py` (size limit, JSON);
  - `outbound/services/webhook.py::verify`, `sign`, `WebhookService.receive`;
  - `outbound/services/intake.py` (field matching, `IntakeService.run`).
- **Tests:** `tests/api/test_security.py` (size limit), `tests/api/test_endpoints.py` (signature, replay, duplicates).
