# One image for every process: the API (`outbound serve`), the worker and one-off CLI commands.
# Secrets are not baked in: `doppler run` fetches them when the container starts (docs/DEPLOY.md).

# ---- the web app -------------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web2
COPY web2/package.json web2/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web2/ ./
RUN npm run build

# ---- uv, pinned to the version the lockfile was made with --------------------------------------
FROM ghcr.io/astral-sh/uv:0.9.26 AS uv

# ---- the Python app ----------------------------------------------------------------------------
FROM python:3.12-slim

# The Doppler CLI from Doppler's signed apt repository.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -sLf --retry 3 --tlsv1.2 --proto "=https" \
        "https://packages.doppler.com/public/cli/gpg.DE2A7741A397C129.key" \
        | gpg --dearmor -o /usr/share/keyrings/doppler-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/doppler-archive-keyring.gpg] https://packages.doppler.com/public/cli/deb/debian any-version main" \
        > /etc/apt/sources.list.d/doppler-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends doppler \
    && apt-get purge -y gnupg && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv
# On a slow link, dozens of parallel downloads share the bandwidth and the larger wheels pass
# uv's 30 s timeout; fewer at a time, with more patience, finishes instead of failing the build.
ENV UV_COMPILE_BYTECODE=1 \
    UV_HTTP_TIMEOUT=300 \
    UV_CONCURRENT_DOWNLOADS=4 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app
# Dependencies first, so a code change does not reinstall them. No dev or legacy groups.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-default-groups --no-install-project
COPY outbound/ ./outbound/
# Installed in place (editable), so outbound/api/app.py finds the web app at /app/web2/dist.
RUN uv sync --frozen --no-default-groups
COPY --from=web /web2/dist ./web2/dist

RUN useradd --create-home --uid 10001 outbound \
    && mkdir -p /doppler && chown outbound /doppler
USER outbound

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

# The fallback is Doppler's encrypted copy of the last secrets, so a restart works while
# Doppler is unreachable. Compose gives each service its own file on the doppler volume.
ENTRYPOINT ["doppler", "run", "--fallback", "/doppler/fallback.json", "--"]
CMD ["outbound", "serve"]
