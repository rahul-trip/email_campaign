<!--
Header to copy into a one-off data-fix script in scripts/. See operations/data-fixes.md for the rules.
-->
```python
"""<One line: what this script corrects, and the incident or run that caused it.>

    uv run python -m scripts.<name>              # prints the plan, changes nothing
    uv run python -m scripts.<name> --apply      # applies it

Rules this script follows (docs/technical/operations/data-fixes.md):
- Dry run by default; --apply is required to change anything.
- Every change goes through a service, so it writes the same events as the app would.
- Every step finds its target by a stable key (domain, then name) and skips itself once done,
  so running the script twice is safe.
- Scoped to one workspace (--workspace, default "default").
- The printed plan may name people and domains, because the operator must be able to check it,
  but it is printed to the terminal only. Nothing personal is written to logs or files.
- Covered by a test on a seeded copy of the data: the plan, the result, and an empty second run.
"""
```
