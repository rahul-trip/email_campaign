---
type: reference
status: accepted
date: 2026-10-19
deciders: "@rahul-trip"
introduced_in: 133fd06 (#11)
---

# 0016. Secrets come from Doppler at container start

## Context

The app needs about a dozen secrets (vendor keys, the LLM key, the mailbox password, the database URL, the session secret). A `.env` file on a shared VM would put all of them on disk where the other app's users and backups can see them.

## Decision

Every container starts as `doppler run --fallback <file> -- outbound …`. The VM holds only a read-only Doppler **service token** for `outbound/prd`, in a mode-600 file written by the deploy workflow. Doppler keeps an encrypted fallback copy on a Docker volume so a restart works while Doppler is unreachable. Non-secret, deployment-fixed values (`DATABASE_BACKEND`, `COOKIE_SECURE`, …) are set in `deploy/compose.yml`.

## Consequences

- **Good:** one token on disk instead of every secret; rotation in one place; separate `dev` and `prd` configs.
- **Bad:** a dependency on Doppler at start (mitigated by the fallback); a Doppler value **overrides** a compose value of the same name, so the deployment-fixed keys must never be added to Doppler ([R-11](../tech-debt-and-risks.md#r-11--p2--configuration-doppler-overrides-compose-not-the-other-way-round)).
- **Follow-ups:** correct the precedence statement in the deployment guide.

## Alternatives considered

| Option | Why not |
|---|---|
| A `.env` file on the VM | Every secret on disk on a shared host |
| GCP Secret Manager | Ties the app to GCP IAM on a VM shared with another project |
| GitHub secrets written to an env file at deploy | Secrets still on disk; rotation needs a redeploy |

## Evidence in the code

- `Dockerfile` (`ENTRYPOINT ["doppler", "run", "--fallback", …]`), `deploy/compose.yml` (per-service fallback files, `doppler` volume), `.github/workflows/deploy.yml` (writes `doppler.env`).
