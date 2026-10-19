#!/usr/bin/env bash
# Runs on the VM, from the release folder the workflow just unpacked:
#   OUTBOUND_HOME=/opt/outbound bash /opt/outbound/releases/<sha>/deploy/remote-deploy.sh <sha>
#
# Builds the image here, switches `current` to this release, starts migrate -> api + worker, and
# waits for /api/health. If anything fails it switches back to the previous release and restarts
# that, then exits non-zero. It only ever touches the compose project `outbound`, so the other
# application on the VM is left alone.
set -euo pipefail

RELEASE="${1:?usage: remote-deploy.sh <release-sha>}"
OUTBOUND_HOME="${OUTBOUND_HOME:-/opt/outbound}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"
PROJECT=outbound
RELEASES="$OUTBOUND_HOME/releases"

# Optional, non-secret settings kept on the VM, such as OUTBOUND_PORT.
# A port passed by the caller (the workflow's `port` input) wins over the file.
port_from_caller="${OUTBOUND_PORT:-}"
if [[ -f "$OUTBOUND_HOME/settings.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$OUTBOUND_HOME/settings.env"
  set +a
fi
OUTBOUND_PORT="${port_from_caller:-${OUTBOUND_PORT:-8010}}"
export OUTBOUND_HOME OUTBOUND_PORT

say() { printf '==> %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

compose() { # compose <release> <args...>
  local release="$1"
  shift
  RELEASE="$release" docker compose -p "$PROJECT" -f "$RELEASES/$release/deploy/compose.yml" "$@"
}

healthy() {
  local url="http://127.0.0.1:$OUTBOUND_PORT/api/health"
  for _ in $(seq 1 30); do
    if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  return 1
}

# ---- preflight -------------------------------------------------------------------------------
command -v docker >/dev/null || die "docker is not installed"
docker compose version >/dev/null 2>&1 || die "the docker compose plugin is not installed"
command -v curl >/dev/null || die "curl is not installed"
[[ -d "$RELEASES/$RELEASE" ]] || die "release $RELEASE is not unpacked in $RELEASES"
[[ -s "$OUTBOUND_HOME/doppler.env" ]] || die "$OUTBOUND_HOME/doppler.env is missing (DOPPLER_TOKEN)"

previous=""
if [[ -L "$OUTBOUND_HOME/current" ]]; then
  previous="$(basename "$(readlink "$OUTBOUND_HOME/current")")"
fi

# ---- build (the only heavy step; low priority so the other app keeps its CPU) -----------------
say "building outbound:$RELEASE"
nice -n 10 env RELEASE="$RELEASE" docker compose -p "$PROJECT" \
  -f "$RELEASES/$RELEASE/deploy/compose.yml" build api

# ---- switch and start --------------------------------------------------------------------------
rollback() {
  say "deploy of $RELEASE failed; recent logs:"
  compose "$RELEASE" logs --tail 100 migrate api worker || true
  if [[ -n "$previous" && "$previous" != "$RELEASE" && -d "$RELEASES/$previous" ]]; then
    say "rolling back to $previous"
    ln -sfn "$RELEASES/$previous" "$OUTBOUND_HOME/current"
    # Migrations are not undone: they are written to be additive, so the old code still runs.
    compose "$previous" up -d --remove-orphans api worker || true
    if healthy; then
      say "rolled back to $previous and it is healthy"
    else
      say "the rollback is not healthy either; look at: docker compose -p $PROJECT logs"
    fi
  else
    say "no earlier release to go back to; stopping $RELEASE"
    compose "$RELEASE" down || true  # keeps the doppler volume
    rm -f "$OUTBOUND_HOME/current"
  fi
  exit 1
}

say "starting $RELEASE (migrate, then api and worker)"
ln -sfn "$RELEASES/$RELEASE" "$OUTBOUND_HOME/current"
compose "$RELEASE" up -d --remove-orphans || rollback
healthy || rollback
say "healthy on 127.0.0.1:$OUTBOUND_PORT"

# ---- tidy up: old release folders and their images, never anything else -----------------------
# Keeps this release, the previous one and the KEEP_RELEASES newest others, for quick rollbacks.
kept=0
while read -r _ release; do
  [[ "$release" == "$RELEASE" || "$release" == "$previous" ]] && continue
  if (( kept < KEEP_RELEASES )); then
    kept=$((kept + 1))
    continue
  fi
  rm -rf "${RELEASES:?}/$release"
  docker image rm "outbound:$release" >/dev/null 2>&1 || true
done < <(find "$RELEASES" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %f\n' | sort -rn)
docker image prune -f --filter "label=com.docker.compose.project=$PROJECT" >/dev/null 2>&1 || true

say "deployed $RELEASE (previous: ${previous:-none})"
