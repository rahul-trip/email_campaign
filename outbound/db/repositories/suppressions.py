"""The do-not-contact list. Only hashes are stored, never the address."""

from __future__ import annotations

from sqlalchemy import select

from outbound.db.models import SuppressionRow
from outbound.db.repositories.base import ScopedRepository, snapshot
from outbound.domain.actors import SYSTEM
from outbound.domain.domains import registrable_domain
from outbound.domain.entities import Suppression
from outbound.domain.enums import EntityType, SuppressionKind, SuppressionReason
from outbound.domain.hashing import hash_value


class SuppressionRepository(ScopedRepository):
    def add(
        self,
        kind: SuppressionKind,
        value: str,
        reason: SuppressionReason,
        *,
        actor: str = SYSTEM,
    ) -> bool:
        """Add an entry. Returns False if the value was already suppressed."""
        digest = hash_value(value)
        if self._exists(kind, digest):
            return False
        row = SuppressionRow(
            workspace_id=self._workspace_id, kind=kind, value_hash=digest, reason=reason
        )
        self._session.add(row)
        self._session.flush()
        self._events.append(
            EntityType.WORKSPACE,
            self._workspace_id,
            "suppression_added",
            actor,
            {"kind": kind.value, "reason": reason.value},  # never the value itself
        )
        return True

    def entries(self) -> list[Suppression]:
        """The list as stored: hashes only, so the UI can show kind, reason and date."""
        stmt = (
            select(SuppressionRow)
            .where(SuppressionRow.workspace_id == self._workspace_id)
            .order_by(SuppressionRow.created_at.desc())
        )
        return [snapshot(row, Suppression) for row in self._session.scalars(stmt)]

    def is_email_suppressed(self, email: str) -> bool:
        return self._exists(SuppressionKind.EMAIL, hash_value(email))

    def is_domain_suppressed(self, domain: str) -> bool:
        root = registrable_domain(domain) or domain
        return self._exists(SuppressionKind.DOMAIN, hash_value(root))

    def blocks(self, email: str) -> bool:
        """True if the address, or its domain, is on the list."""
        return self.is_email_suppressed(email) or self.is_domain_suppressed(email)

    def _exists(self, kind: SuppressionKind, digest: str) -> bool:
        stmt = select(SuppressionRow.id).where(
            SuppressionRow.workspace_id == self._workspace_id,
            SuppressionRow.kind == kind,
            SuppressionRow.value_hash == digest,
        )
        return self._session.scalars(stmt).first() is not None
