---
type: reference
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# GitHub Actions

GitHub Actions runs CI on every push to `main` and every pull request, and the manual deploy workflow. Each job is described in [CI/CD](../quality/ci-cd.md); this page covers what the platform holds and how it is trusted.

## Workflows

| Workflow | Trigger | Does |
|---|---|---|
| `.github/workflows/ci.yml` (`ci`) | push to `main`, pull request, `workflow_call` | Lint and types; tests on SQLite and on Postgres 16; `web` and `web2` builds and browser tests (with a stale-client check); Docker image build; security (gitleaks over full history, pip-audit, npm audit) |
| `.github/workflows/deploy.yml` (`deploy`) | `workflow_dispatch` (manual) | Optionally runs `ci.yml`, then deploys a commit to the VM over SSH |
| `.github/dependabot.yml` | weekly | Update PRs for `uv`, `npm` in `/web` (not `/web2`) and GitHub Actions ([R-16](../tech-debt-and-risks.md#r-16--p2--supply-chain-gaps-in-update-and-pinning-coverage)) |

## The deploy workflow

- **Inputs:**
  - `host`;
  - `username` (in the VM's `docker` group);
  - `ref` (default `main`);
  - `port` (blank keeps the VM's setting, else 8010);
  - `app_dir` (default `/opt/outbound`);
  - `run_checks` (default true).
- **Environment:** `production`. Add *required reviewers* there to make deploys need an approval.
- **Secrets** (in that environment):

  | Secret | What it is |
  |---|---|
  | `DEPLOY_SSH_KEY` | The private half of a deploy-only key |
  | `DOPPLER_TOKEN` | The read-only service token for `outbound/prd` |
  | `SSH_KNOWN_HOSTS` | Optional: the VM's host key line. **Without it the workflow runs `ssh-keyscan` and trusts the first key it sees** |

- **Concurrency:** one deploy per host at a time (`deploy-<host>`), never cancelled mid-way.
- **Permissions:** `contents: read`.
- **Timeout:** 30 minutes.
- **Steps:**
  1. Validate the inputs.
  2. Check out the ref and take its 12-character SHA.
  3. Set up SSH.
  4. Upload the code with `git archive | ssh tar` into `releases/<sha>`.
  5. Write `doppler.env`.
  6. Run `deploy/remote-deploy.sh <sha>` on the VM.
  7. Write a summary and delete the key.

  The release mechanics, and the rollback defect, are in [release and rollback](../operations/release-and-rollback.md).

## Trust and hardening

| Item | State |
|---|---|
| A user in the VM's `docker` group | Effectively root on the VM. Keep the key only in GitHub's environment secrets |
| Action pinning | By major tag (`@v4`, `@v5`, `@v2`), not by commit SHA ([R-16](../tech-debt-and-risks.md#r-16--p2--supply-chain-gaps-in-update-and-pinning-coverage)) |
| Host key | Trusted on first use unless `SSH_KNOWN_HOSTS` is set; set it |
| Image | Built on the VM, not in Actions; not scanned or signed |
