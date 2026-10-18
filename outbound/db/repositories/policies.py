"""Country policies. Versioned: every change bumps ``version``, which each decision records."""

from __future__ import annotations

from sqlalchemy import select

from outbound.db.models import CountryPolicyRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.db.types import utcnow
from outbound.domain.entities import CountryPolicy


class CountryPolicyRepository(ScopedRepository):
    def get(self, country_code: str) -> CountryPolicy | None:
        stmt = select(CountryPolicyRow).where(
            CountryPolicyRow.workspace_id == self._workspace_id,
            CountryPolicyRow.country_code == country_code.upper(),
        )
        row = self._session.scalars(stmt).one_or_none()
        return snapshot(row, CountryPolicy) if row else None

    def all(self) -> list[CountryPolicy]:
        stmt = (
            select(CountryPolicyRow)
            .where(CountryPolicyRow.workspace_id == self._workspace_id)
            .order_by(CountryPolicyRow.country_code)
        )
        return [snapshot(row, CountryPolicy) for row in self._session.scalars(stmt)]

    def upsert(self, policy: CountryPolicy, *, reviewer: str | None = None) -> CountryPolicy:
        """Create or change a country's policy. A real change bumps the version, which every
        later decision records, so an audit can tell which rules a lead was judged by."""
        row = self._session.scalars(
            select(CountryPolicyRow).where(
                CountryPolicyRow.workspace_id == self._workspace_id,
                CountryPolicyRow.country_code == policy.country_code.upper(),
            )
        ).one_or_none()
        provenance = (
            [p.value for p in policy.allowed_provenance]
            if policy.allowed_provenance is not None
            else None
        )
        if row is None:
            row = CountryPolicyRow(
                workspace_id=self._workspace_id,
                country_code=policy.country_code.upper(),
                rule=policy.rule,
                requires_corporate_subscriber=policy.requires_corporate_subscriber,
                allowed_provenance=provenance,
                footer_template=policy.footer_template,
                version=1,
            )
            self._session.add(row)
        else:
            changed = (
                row.rule != policy.rule
                or row.requires_corporate_subscriber != policy.requires_corporate_subscriber
                or row.allowed_provenance != provenance
                or row.footer_template != policy.footer_template
            )
            if changed:
                row.rule = policy.rule
                row.requires_corporate_subscriber = policy.requires_corporate_subscriber
                row.allowed_provenance = provenance
                row.footer_template = policy.footer_template
                row.version += 1
        if reviewer:
            row.reviewed_by = reviewer
            row.reviewed_at = utcnow()
        self._session.flush()
        return snapshot(row, CountryPolicy)

    def add_if_missing(self, policy: CountryPolicy) -> bool:
        """Seed a row without ever overwriting one that exists (it may have been edited)."""
        if self.get(policy.country_code) is not None:
            return False
        self._session.add(
            CountryPolicyRow(
                workspace_id=self._workspace_id,
                country_code=policy.country_code.upper(),
                rule=policy.rule,
                requires_corporate_subscriber=policy.requires_corporate_subscriber,
                allowed_provenance=(
                    [p.value for p in policy.allowed_provenance]
                    if policy.allowed_provenance is not None
                    else None
                ),
                footer_template=policy.footer_template,
                version=policy.version,
                reviewed_by=policy.reviewed_by,
            )
        )
        self._session.flush()
        return True
