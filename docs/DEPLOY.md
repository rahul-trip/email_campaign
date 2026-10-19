# Deploying Outbound to a VM

Outbound runs on a Linux VM (a GCP Compute Engine instance that also hosts another application) as three Docker containers in their own compose project. A GitHub Actions workflow deploys any commit given only the VM's address and an SSH user.

```
GitHub Actions ─ "deploy" workflow (host, username, ref)
   │  ssh, git archive of the commit
   ▼
VM  /opt/outbound/
      releases/<sha>/          the code of each deployed commit (the last few are kept)
      current -> releases/<sha>
      doppler.env              DOPPLER_TOKEN only, mode 600
      settings.env             optional, non-secret: OUTBOUND_PORT
    docker compose -p outbound  (never touches the other app's containers)
      migrate   one-shot: outbound db upgrade && outbound seed
      api       outbound serve  → 127.0.0.1:8010  ← the VM's existing nginx/Caddy adds https
      worker    outbound worker
    Supabase Postgres (session pooler, TLS)  ← DATABASE_URL, from Doppler
```

- **Secrets live in Doppler.** Every container starts as `doppler run -- outbound …`. The VM holds only a read-only Doppler service token. Doppler also keeps an encrypted copy of the last secrets on the `outbound_doppler` volume, so a restart works while Doppler is unreachable.
- **The database is Supabase Postgres.** The VM reaches it over the internet, encrypted; nothing database-related runs on the VM.
- **The image is built on the VM** from the `Dockerfile`, at low CPU priority. There is no registry.
- **HTTPS is the job of the proxy already on the VM.** The app publishes its port on `127.0.0.1` only and sets `COOKIE_SECURE=true`. It refuses logins over plain http, so it is never reachable without the proxy.

## 1. One-time setup

### 1.1 The VM

As a user with sudo on the VM:

```bash
# Docker Engine and the compose plugin (skip if the other app already uses Docker)
curl -fsSL https://get.docker.com | sh

# A deploy user that may run docker and owns the app folder
sudo useradd --create-home --shell /bin/bash deploy
sudo usermod -aG docker deploy
sudo install -d -o deploy -g deploy /opt/outbound
sudo -u deploy install -d -m 700 /home/deploy/.ssh
# paste the public half of the deploy key (see 1.4):
sudo -u deploy tee -a /home/deploy/.ssh/authorized_keys < deploy_key.pub
```

The VM also needs `curl`. It needs outbound access to `packages.doppler.com` and `api.doppler.com`, to the vendors' APIs, and to the IMAP server on port 993. A user in the `docker` group is effectively root on the VM, so keep the key in GitHub secrets only.

If port 8010 is taken by the other app, choose another. Either put `OUTBOUND_PORT=8020` in `/opt/outbound/settings.env` or pass `port` when running the workflow.

### 1.2 The database (Supabase Postgres)

The data lives in a Supabase project, reached through its **session pooler**. From the dashboard, **Connect → Session pooler** gives a URL like this:

```
postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

- **Use the session pooler on port 5432**, not the direct connection, which is IPv6-only and so out of reach of most GCP VMs. Do not use the transaction pooler on port 6543 either: it breaks the prepared statements psycopg uses.
- Replace `[YOUR-PASSWORD]` with the database password (**Project Settings → Database**). URL-encode it if it contains `@`, `:`, `/`, `#` or `?`.
- Add `?sslmode=require` at the end, so the connection is always encrypted.
- Store the result in Doppler as `DATABASE_URL`. `postgresql://` is fine: the app switches it to the psycopg 3 driver by itself.
- Small Supabase plans allow about 15 pooler clients in all. Each process (api, worker, a one-off CLI command) keeps `DATABASE_POOL_SIZE` connections (default 5). Lower it in Doppler if Supabase reports `max clients reached`.

The first deploy creates the tables (`db upgrade`) and the default workspace, campaign and country rules (`seed`). Both are safe to run again, and every deploy runs them. The tables go in the `public` schema, so use a Supabase project of its own, or at least one where nothing else owns tables with the same names.

Migrations are additive. A rollback to an older commit does not undo them, and the older code runs on the newer schema.

### 1.3 Doppler

1. Create a project `outbound` with a `prd` config.
2. Add every key from [`.env.example`](../.env.example) that you use, plus:
   - `DATABASE_URL`, the Supabase URL from 1.2;
   - `OPERATOR_PASSWORD_HASH`, from `uv run outbound auth hash-password`;
   - `SESSION_SECRET`, a long random string (`openssl rand -hex 32`).
   From a filled-in local `.env`: `doppler secrets upload --project outbound --config prd .env`. Then remove keys that are only for your laptop.
3. Do **not** put `ENVIRONMENT`, `LOG_FORMAT`, `API_HOST`, `API_PORT`, `COOKIE_SECURE` or `FORWARDED_ALLOW_IPS` there. `deploy/compose.yml` sets them, and the compose values win.
4. Create a **service token** for `outbound/prd` with read access. That is the `DOPPLER_TOKEN` secret below. Never use a personal token (`dp.pt.…`) for the VM: it can read and change every project you can.

### 1.4 GitHub

1. Make an SSH key just for deploying: `ssh-keygen -t ed25519 -N '' -f deploy_key`.
2. Repository **Settings → Environments → New environment** `production`. Add *Required reviewers* if deploys need an approval. Add these secrets:

| Secret | Value |
|---|---|
| `DEPLOY_SSH_KEY` | contents of `deploy_key` (the private half) |
| `DOPPLER_TOKEN` | the Doppler service token from 1.3 |
| `SSH_KNOWN_HOSTS` | optional but recommended: `ssh-keyscan <vm-host>` output. Without it, the first key seen is trusted. |

### 1.5 The proxy

Add a site for Outbound to the proxy that already runs on the VM. Copy [`deploy/nginx.conf.example`](../deploy/nginx.conf.example) or [`deploy/Caddyfile.example`](../deploy/Caddyfile.example), replace the domain, point the domain's DNS at the VM, and reload the proxy. The proxy must send `X-Forwarded-For`: the login throttle and the logs read the client's address from it.

## 2. Deploying

**Actions → deploy → Run workflow**, then fill in:

| Input | Example | Notes |
|---|---|---|
| host | `34.89.10.20` or `vm.example.com` | |
| username | `deploy` | must be in the `docker` group |
| ref | `main` | branch, tag or commit |
| port | blank | blank keeps `settings.env`, else 8010 |
| app_dir | `/opt/outbound` | |
| run_checks | ✓ | runs the whole CI suite first |

The workflow then:

1. runs CI;
2. uploads the commit to `releases/<sha>`;
3. writes `doppler.env`;
4. runs [`deploy/remote-deploy.sh`](../deploy/remote-deploy.sh) on the VM. The script builds the image, points `current` at the new release, starts `migrate` and then `api` and `worker`, and waits up to a minute for `/api/health`.

If anything fails, the script prints the last logs, switches back to the previous release and restarts it, and the workflow fails. A deploy restarts the app for a few seconds. **Deploy when no run is in progress.** Until Phase 3b item B3 (stale runs) is done, a run whose worker is stopped mid-way stays `running` in the Runs screen. The leads it already finished keep their results.

**Rolling back:** run the workflow again with the older commit or tag as `ref`. Its image is usually still on the VM, so it starts quickly.

## 3. Day to day on the VM

```bash
cd /opt/outbound/current
export RELEASE=$(basename "$(readlink /opt/outbound/current)")
alias oc='docker compose -p outbound -f deploy/compose.yml'

oc ps                                   # what is running
oc logs -f worker                       # follow the worker (JSON lines)
oc logs --since 1h api | grep '"level": "error"'
oc restart worker
oc run --rm --no-deps api outbound status        # any CLI command, with the real secrets
oc run --rm --no-deps api outbound report cost --days 7
```

Moving the data from a laptop's SQLite file is not automatic. Start on the empty Supabase database (the first deploy sets it up), then re-add targets. If the legacy workbook is needed, copy it to the VM and run `oc run --rm --no-deps -v "$PWD/book.xlsx:/tmp/book.xlsx:ro" api outbound import-legacy-xlsx /tmp/book.xlsx`.

## 4. When something is wrong

| Symptom | Cause and fix |
|---|---|
| `doppler.env is missing` | The workflow writes it; check the `DOPPLER_TOKEN` secret. |
| `Doppler Error: … token` in the logs | The token is wrong or revoked. Make a new service token and update the secret. |
| `migrate` exits with `password authentication failed` | The password in `DATABASE_URL` is wrong, still `[YOUR-PASSWORD]`, or not URL-encoded (1.2). |
| `migrate` exits with `Network is unreachable` | `DATABASE_URL` is the direct connection (IPv6). Use the session pooler URL (1.2). |
| `max clients reached` in the logs | Too many connections for the Supabase plan. Lower `DATABASE_POOL_SIZE` in Doppler. |
| The worker restarts every few seconds, logging `not configured: …` | A vendor key named in the message is missing in Doppler. |
| The login page loads but signing in fails with a cookie error | The site is not on https, or the proxy does not forward to the app. |
| Every login is throttled together | The proxy does not send `X-Forwarded-For`. |
| `port is already allocated` | Another app uses `OUTBOUND_PORT`. Choose another (1.1) and update the proxy. |

The compose file's `env_file` treats `$` as a variable. That does not matter for `doppler.env`, which holds only the token, but an Argon2 hash pasted into an env file for a local test must be in single quotes.
