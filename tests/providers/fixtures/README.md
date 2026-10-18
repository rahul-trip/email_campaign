# Provider fixtures

These JSON files are **hand-built from each vendor's public documentation**: the example
responses and field lists, not captures from a live account. They prove the adapters map the
documented shapes correctly. They do not prove the vendors behave exactly this way.

During the Phase 0 bake-off, run `uv run python -m scripts.bakeoff --record data/private/recorded`
with real keys. That saves every raw vendor response. Review the files, remove personal data,
and replace the matching fixture here. Until then, treat a passing adapter test as a statement
about the documentation only.

Scrubby is the weakest case: its public reference documents only the `pending` response, so its
`valid`, `invalid` and `catch-all` fixtures are guesses at the result shape.

Fixtures added in Phase 2, also hand-built from documentation:

- `llm/chat.json`: an OpenAI-compatible chat completion with token usage.
- `companies_house/search.json`: a Companies House company search.

The IMAP adapter has no fixtures: its tests use an in-memory IMAP server (`tests/providers/test_imap_mailbox.py`). Like Scrubby and Companies House, it needs one live check against the real mailbox.
