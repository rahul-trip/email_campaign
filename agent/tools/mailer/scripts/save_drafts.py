#!/usr/bin/env python3
"""Thin CLI wrapper around agent.tools.mailer.core.campaign_runner.sync_campaign_to_drafts.

This exists for manual/local runs and smoke-testing. The real integration
point for the agent graph is the function itself (used via
agent/tools/drafts_tool.py), not this script.

Usage (run from the project root, email_capaign/):
    python -m agent.tools.mailer.scripts.save_drafts --dry-run
    python -m agent.tools.mailer.scripts.save_drafts --dry-run --limit 2
    python -m agent.tools.mailer.scripts.save_drafts
    python -m agent.tools.mailer.scripts.save_drafts --xlsx /path/to/other_matrix.xlsx
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `agent.tools.mailer...` imports resolve
# even when this file is invoked directly (python agent/tools/mailer/scripts/save_drafts.py).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agent.tools.mailer.core.campaign_runner import sync_campaign_to_drafts  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xlsx", dest="xlsx_path", default=None, help="Override XLSX_PATH from .env")
    parser.add_argument("--dry-run", action="store_true", help="Preview without connecting to any mailbox")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N rows")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    result = sync_campaign_to_drafts(xlsx_path=args.xlsx_path, dry_run=args.dry_run, limit=args.limit)

    print(json.dumps(result.as_dict(), indent=2))

    if result.errors:
        return 1
    return 0 if result.failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
