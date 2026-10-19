#!/usr/bin/env bash
# Rehearse a deploy on this machine before doing it on the VM (docs/DEPLOY.md, section 5).
#
#   deploy/local-test.sh up      copy the working tree into .deploy-local/releases/, then run the
#                                VM's own deploy script on it, plus a local Postgres and https proxy
#   deploy/local-test.sh logs    follow the logs
#   deploy/local-test.sh down    stop everything (the local database is kept)
#   deploy/local-test.sh reset   stop everything and delete the local database
#
# Secrets come from Doppler, as on the VM: put a service token for the outbound *dev* config in
# .deploy-local/doppler.env as DOPPLER_TOKEN=... (git-ignored).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export OUTBOUND_HOME="$ROOT/.deploy-local"
export OUTBOUND_PORT="${OUTBOUND_PORT:-8010}"
export OUTBOUND_COMPOSE_EXTRA=deploy/compose.local.yml

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

current_compose() { # the compose command for the release that is running now
  [[ -L "$OUTBOUND_HOME/current" ]] || die "nothing deployed yet; run: deploy/local-test.sh up"
  local release
  release="$(basename "$(readlink "$OUTBOUND_HOME/current")")"
  RELEASE="$release" docker compose -p outbound \
    -f "$OUTBOUND_HOME/current/deploy/compose.yml" \
    -f "$OUTBOUND_HOME/current/$OUTBOUND_COMPOSE_EXTRA" "$@"
}

case "${1:-up}" in
  up)
    command -v docker >/dev/null || die "docker is not installed"
    [[ -s "$OUTBOUND_HOME/doppler.env" ]] ||
      die "put DOPPLER_TOKEN=<service token for outbound/dev> in .deploy-local/doppler.env"
    release="local-$(date +%Y%m%d%H%M%S)"
    mkdir -p "$OUTBOUND_HOME/releases/$release"
    # What git would ship, including uncommitted changes, but never ignored files such as .env.
    (cd "$ROOT" && git ls-files -co --exclude-standard -z | tar --null -T - -cf -) |
      tar -xf - -C "$OUTBOUND_HOME/releases/$release"
    bash "$OUTBOUND_HOME/releases/$release/deploy/remote-deploy.sh" "$release"
    printf '\nOpen https://localhost:8443 (accept the local certificate once).\n'
    ;;
  logs) current_compose logs -f --tail 50 ;;
  down) current_compose down ;;
  reset) current_compose down --volumes ;;
  *) die "usage: deploy/local-test.sh [up|logs|down|reset]" ;;
esac
