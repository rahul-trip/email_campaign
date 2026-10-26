---
type: how-to
status: draft
owner: "@rahul-trip"
last_verified: 2026-10-21 (6deda34)
applies_to: Phase 3b
---

# Add a migration

1. **Change the model** in `outbound/db/models.py` (and the entity in `outbound/domain/entities.py` if callers need the field).
2. **Draft the revision.** With a migrated development database, call `outbound.db.migrate.generate(url, "short message")` from a Python shell, or write it by hand. Name it `00NN_<what>.py` and chain `down_revision` to the current head.
3. **Make it frozen and portable:**
   - literal values and no application imports;
   - `op.batch_alter_table` for every alter;
   - named constraints;
   - `sqlite_where` and `postgresql_where` on partial indexes;
   - a `CHECK` widened by drop-and-recreate *by name*.
4. **Make it additive.** Add nullable or defaulted columns, never drop or rename in the same release ([expand/contract](../data/migrations.md#rules)). The previous release must run on the new schema.
5. **Write a safe downgrade**, or one that refuses with a reason when it would lose data or a decision.
6. **Test it on both databases:**

   ```bash
   uv run pytest tests/db/test_migrations.py tests/db -q
   uv run --with pgserver python -m scripts.pg_tests tests/db -q
   ```

   `test_the_migrated_schema_matches_the_models` and the `CHECK`-versus-enum tests must pass.
7. **Docs in the same PR:**
   - [schema](../data/schema.md): the table block, and §7 "Value conventions" if a JSON key or rule changed;
   - the [migration log](../data/migrations.md#log);
   - the module's LLD.
8. **Deploy.** `migrate` runs it on the next deploy. Know the rollback caveat ([R-01](../tech-debt-and-risks.md#r-01--p0--operations-a-rollback-after-a-migration-leaves-the-app-down)): if the deploy fails after the migration ran, roll forward.
