---
type: reference
status: accepted
date: 2026-10-19
deciders: "@rahul-trip"
introduced_in: 133fd06, 4910619 (#11)
---

# 0015. One Docker image, built on the VM, run as three containers

## Context

Production is a shared GCP VM that already runs another application behind its own reverse proxy. There is no container registry, and deploys are rare and manual. The API, worker and migration step share all their code.

## Decision

One multi-stage `Dockerfile` builds `web2` with Node, installs the Python app with `uv sync --frozen` (no dev or legacy groups), and runs as a non-root user. The image is built **on the VM** from a `git archive` of the deployed commit and tagged `outbound:<sha>`. A compose project `outbound` runs it as `migrate` (one-shot), `api` (loopback port behind the VM's proxy) and `worker`. The last releases' folders and images are kept for rollback.

## Consequences

- **Good:** no registry to run or pay for; the compose project never touches the other app; a rollback to a recent release reuses its local image.
- **Bad:** builds load the shared VM; images are not scanned or signed; base images are pinned by tag, not digest ([R-16](../tech-debt-and-risks.md#r-16--p2--supply-chain-gaps-in-update-and-pinning-coverage)); the rollback path re-runs the old `migrate` and fails after a migration ([R-01](../tech-debt-and-risks.md#r-01--p0--operations-a-rollback-after-a-migration-leaves-the-app-down)).
- **Follow-ups:** fix the rollback; add an image scan; pin base images by digest.

## Alternatives considered

| Option | Why not |
|---|---|
| Build in CI and push to GHCR; pull on the VM | A registry and its credentials for a single host; may be adopted later |
| A PaaS (Fly.io, Render, Cloud Run) | The VM and its proxy already exist; IMAP and the worker are long-running |
| Run with systemd and a virtualenv | Less isolation from the other app; harder rollback |

## Evidence in the code

- `Dockerfile`, `.dockerignore`, `deploy/compose.yml`, `deploy/remote-deploy.sh`, `.github/workflows/deploy.yml`; CI job `image`.
