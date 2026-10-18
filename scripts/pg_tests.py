"""Run the tests against a throwaway PostgreSQL, with no Docker and nothing installed.

``pgserver`` bundles real Postgres binaries and starts a private server in a temp folder, which
is deleted afterwards. Everything after the command is passed to pytest::

    uv run --with pgserver python -m scripts.pg_tests tests/db -q

CI uses a Postgres service container instead; this is for your own machine.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

import pgserver


def main(pytest_args: list[str]) -> int:
    with tempfile.TemporaryDirectory() as data_dir:
        server = pgserver.get_server(data_dir, cleanup_mode="stop")
        try:
            url = server.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
            env = {**os.environ, "TEST_DATABASE_URL": url}
            return subprocess.call([sys.executable, "-m", "pytest", *pytest_args], env=env)
        finally:
            server.cleanup()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
