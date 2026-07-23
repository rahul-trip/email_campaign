#!/usr/bin/env python3
"""One-off utility: connect to the configured IMAP mailbox and print all folder
names, so you can find the exact Drafts folder path for DRAFTS_FOLDER in .env.

Hostinger/Titan mailboxes commonly expose it as "Drafts", but some IMAP layouts
use "INBOX.Drafts" or similar — this removes the guesswork.

Usage (run from the project root, email_capaign/):
    python -m agent.tools.mailer.scripts.list_folders
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from agent.tools.mailer.config.settings import Settings  # noqa: E402
from agent.tools.mailer.drafts.imap_provider import ImapDraftProvider  # noqa: E402


def main() -> int:
    settings = Settings.from_env()
    problems = settings.validate(require_credentials=True)
    # Folder listing doesn't need the xlsx to exist.
    problems = [p for p in problems if "XLSX_PATH" not in p]
    if problems:
        for p in problems:
            print(f"CONFIG ERROR: {p}")
        return 1

    provider = ImapDraftProvider(settings)
    provider.connect()
    try:
        for folder in provider.list_folders():
            print(folder)
    finally:
        provider.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
