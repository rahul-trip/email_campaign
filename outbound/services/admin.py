"""What platform admins do to customers (Phase 6d): plans, limits, credits, access, status,
people, platform settings and the audit log.

Every change is made through the platform unit of work with its audit row in the *same*
transaction, so a change without a record cannot happen. Figures across customers are counts and
sums only. An admin sees a customer's plan, use and members, never the content of its leads;
only the alpha's superadmin can open a workspace, and then read-only.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from outbound.db.errors import NotFound
from outbound.db.identity import IdentityUnitOfWorkFactory
from outbound.db.platform import PlatformUnitOfWork, PlatformUnitOfWorkFactory
from outbound.db.repositories.workspaces import MailboxView
from outbound.db.types import utcnow
from outbound.db.uow import UnitOfWorkFactory
from outbound.domain.entities import Membership, User, Workspace
from outbound.domain.entitlements import (
    UNLIMITED,
    AccessLevel,
    Grant,
    Override,
    Plan,
    PlanAssignment,
    Quota,
    StepQuota,
    compute_quota,
    period_bounds,
)
from outbound.domain.enums import PlatformRole, UsageStep, UserStatus, WorkspaceStatus
from outbound.domain.errors import InvalidInput
from outbound.domain.platform_settings import PlatformSettings
from outbound.logging import get_logger
from outbound.services.intake import IntakeService
from outbound.services.resume import Released, ResumeService

log = get_logger(__name__)

OVERRIDE_KEYS = frozenset(
    {"seats", "mailboxes", "active_campaigns", "max_leads_per_run", "max_prospect_budget"}
)
SOON = timedelta(days=7)
SUPER = PlatformRole.SUPERADMIN
ANSWERED = ("credits_granted", "credits_dismissed")


@dataclass(frozen=True)
class CustomerRow:
    workspace: Workspace
    plan: Plan
    quota: Quota
    spend_micro_usd: int  # this calendar month
    leads: int
    members: int
    mailboxes: int
    mailbox_problems: int
    waiting: int
    last_active: datetime | None
    open_request: bool

    @property
    def near_limit(self) -> bool:
        return any(
            s.limit and (s.used / s.limit >= 0.8) for s in self.quota.steps.values() if s.limit
        )


@dataclass(frozen=True)
class CustomerDetail:
    row: CustomerRow
    assignment: PlanAssignment | None
    overrides: list[Override]
    grants: list[Grant]
    members: list[tuple[Membership, User]]
    mailboxes: list[MailboxView]
    requests: list[dict[str, Any]]
    activity: list[dict[str, Any]]


@dataclass(frozen=True)
class UserRow:
    user: User
    workspaces: list[tuple[str, str]]  # (workspace name, role)


@dataclass(frozen=True)
class Attention:
    kind: str  # credit_request, access_ending, mailbox
    workspace_id: str
    workspace_name: str
    detail: str


@dataclass(frozen=True)
class Overview:
    customers: int
    expiring: int
    leads_added: int
    drafts_made: int
    spend_micro_usd: int
    spend_by_provider: dict[str, int]
    waiting: int
    waiting_customers: int
    attention: list[Attention]
    activity: list[dict[str, Any]]


class AdminError(Exception):
    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


class AdminService:
    def __init__(
        self,
        platform: PlatformUnitOfWorkFactory,
        identity: IdentityUnitOfWorkFactory,
        uow: UnitOfWorkFactory,
        *,
        now: Callable[[], datetime] = utcnow,
    ) -> None:
        self._platform = platform
        self._identity = identity
        self._uow = uow
        self._now = now

    # ------------------------------------------------------------------ reading

    def overview(self) -> Overview:
        now = self._now()
        month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with self._platform() as p:
            settings, _ = p.settings.get()
            rows = self._rows(p, settings, now)
            figures = p.figures
            start, end = month, month + timedelta(days=32)
            end = end.replace(day=1)
            by_provider = figures.spend_by_provider(start, end)
            leads, drafts = figures.leads_added(start, end), figures.drafts_made(start, end)
            activity = p.audit.recent(limit=12)
        names = {r.workspace.id: r.workspace.name for r in rows}
        attention = [
            Attention("credit_request", r.workspace.id, r.workspace.name, "asked for more credits")
            for r in rows
            if r.open_request
        ]
        attention += [
            Attention(
                "access_ending", r.workspace.id, r.workspace.name,
                f"access ends {r.quota.access_until:%d %b}",
            )
            for r in rows
            if r.quota.access_until and now < r.quota.access_until <= now + SOON
        ]  # fmt: skip
        attention += [
            Attention("mailbox", r.workspace.id, r.workspace.name, "a mailbox needs attention")
            for r in rows
            if r.mailbox_problems
        ]
        return Overview(
            customers=sum(r.workspace.status is WorkspaceStatus.ACTIVE for r in rows),
            expiring=sum(
                bool(r.quota.access_until and now < r.quota.access_until <= now + SOON)
                for r in rows
            ),
            leads_added=leads,
            drafts_made=drafts,
            spend_micro_usd=sum(by_provider.values()),
            spend_by_provider=by_provider,
            waiting=sum(r.waiting for r in rows),
            waiting_customers=sum(1 for r in rows if r.waiting),
            attention=attention,
            activity=[{**a, "workspace": names.get(a["workspace_id"] or "", "")} for a in activity],
        )

    def customers(
        self,
        *,
        search: str = "",
        plan: str | None = None,
        access: str | None = None,
        near_limit: bool = False,
        waiting: bool = False,
        mailbox_problem: bool = False,
    ) -> list[CustomerRow]:
        now = self._now()
        with self._platform() as p:
            settings, _ = p.settings.get()
            rows = self._rows(p, settings, now)
        needle = search.strip().lower()
        if needle:
            rows = [
                r for r in rows
                if needle in r.workspace.name.lower() or needle in r.workspace.slug
            ]  # fmt: skip
        if plan:
            rows = [r for r in rows if r.plan.code == plan]
        if access:
            rows = [r for r in rows if r.quota.access.value == access]
        if near_limit:
            rows = [r for r in rows if r.near_limit]
        if waiting:
            rows = [r for r in rows if r.waiting]
        if mailbox_problem:
            rows = [r for r in rows if r.mailbox_problems]
        return sorted(rows, key=lambda r: r.workspace.name.lower())

    def customer(self, workspace_id: str) -> CustomerDetail:
        now = self._now()
        with self._platform() as p:
            settings, _ = p.settings.get()
            row = next(
                (r for r in self._rows(p, settings, now) if r.workspace.id == workspace_id), None
            )
            if row is None:
                raise NotFound(f"workspace {workspace_id}")
            assignment = p.plans.assignment(workspace_id)
            overrides, grants = p.plans.overrides(workspace_id), p.plans.grants(workspace_id)
            activity = p.audit.recent(workspace_id=workspace_id, limit=100)
        with self._identity() as ids:
            members = ids.memberships.members(workspace_id)
        with self._uow(workspace_id) as uow:
            mailboxes = uow.mailboxes.all()
        return CustomerDetail(
            row, assignment, overrides, grants, members, mailboxes,
            [a for a in activity if a["action"] == "credits_requested"][:5], activity,
        )  # fmt: skip

    # ------------------------------------------------------------------ plan, access, status

    def set_plan(self, workspace_id: str, code: str, *, by: str, note: str = "") -> None:
        with self._platform() as p:
            settings, _ = p.settings.get()
            if code != UNLIMITED.code and code not in settings.plans:
                raise AdminError(422, "unknown_plan", f"There is no plan {code!r}.")
            before = p.plans.assignment(workspace_id)
            p.plans.set_plan(workspace_id, code)
            p.audit.record(
                "plan_changed", actor_user_id=by, workspace_id=workspace_id,
                target_type="workspace", target_id=workspace_id, note=note or None,
                data={"from": before.plan_code if before else None, "to": code},
            )  # fmt: skip
            p.commit()

    def extend_access(
        self,
        workspace_id: str,
        *,
        by: str,
        days: int | None = None,
        until: datetime | None = None,
        note: str = "",
    ) -> datetime | None:
        """Give more time: ``days`` from the later of now and the current end, or an exact date.
        A workspace that was read-only reopens at once."""
        now = self._now()
        with self._platform() as p:
            current = p.plans.assignment(workspace_id)
            if current is None:
                raise AdminError(409, "no_plan", "This workspace has no plan with an end to move.")
            if until is None:
                if not days or days < 1:
                    raise InvalidInput("say how many days, or give a date")
                base = max(now, current.access_until or now)
                until = base + timedelta(days=days)
            if until <= now:
                raise InvalidInput("the new end must be in the future")
            p.plans.set_access_until(workspace_id, until)
            p.audit.record(
                "access_extended", actor_user_id=by, workspace_id=workspace_id,
                target_type="workspace", target_id=workspace_id, note=note or None,
                data={"from": current.access_until.isoformat() if current.access_until else None,
                      "to": until.isoformat()},
            )  # fmt: skip
            p.commit()
        return until

    def set_status(
        self, workspace_id: str, status: WorkspaceStatus, *, by: str, note: str = ""
    ) -> None:
        if status not in (
            WorkspaceStatus.ACTIVE,
            WorkspaceStatus.PAUSED,
            WorkspaceStatus.SUSPENDED,
        ):
            raise InvalidInput("a workspace is made active, paused or suspended here")
        with self._platform() as p:
            before = p.workspaces.get(workspace_id)
            if before is None:
                raise NotFound(f"workspace {workspace_id}")
            if before.status is not status:
                p.workspaces.set_status(workspace_id, status)
            p.audit.record(
                "status_changed", actor_user_id=by, workspace_id=workspace_id,
                target_type="workspace", target_id=workspace_id, note=note or None,
                data={"from": before.status.value, "to": status.value},
            )  # fmt: skip
            p.commit()
        if status is WorkspaceStatus.SUSPENDED:
            with self._identity() as ids:  # everyone in it is signed out of it
                for member, _ in ids.memberships.members(workspace_id):
                    ids.sessions.revoke_for_user(member.user_id)
                ids.commit()

    # ------------------------------------------------------------------ overrides and credits

    def set_override(
        self,
        workspace_id: str,
        key: str,
        value: int | bool | None,
        *,
        by: str,
        expires_at: datetime | None = None,
        note: str = "",
    ) -> Override:
        kind, _, name = key.partition(".")
        known_step = kind == "limit" and name in {s.value for s in UsageStep}
        known_feature = kind == "feature" and bool(name)
        if not (known_step or known_feature or key in OVERRIDE_KEYS):
            raise InvalidInput(f"{key!r} is not something that can be overridden")
        if isinstance(value, int) and not isinstance(value, bool) and value < 0:
            raise InvalidInput("a limit cannot be negative")
        with self._platform() as p:
            added = p.plans.add_override(
                workspace_id, key, value, expires_at=expires_at, note=note, set_by=by
            )
            p.audit.record(
                "override_set", actor_user_id=by, workspace_id=workspace_id, target_type="override",
                target_id=added.id, note=note or None,
                data={"key": key, "value": value,
                      "expires_at": expires_at.isoformat() if expires_at else None},
            )  # fmt: skip
            p.commit()
        return added

    def revoke_override(self, workspace_id: str, override_id: str, *, by: str) -> None:
        with self._platform() as p:
            revoked = p.plans.revoke_override(workspace_id, override_id)
            p.audit.record(
                "override_revoked", actor_user_id=by, workspace_id=workspace_id,
                target_type="override", target_id=override_id, data={"key": revoked.key},
            )  # fmt: skip
            p.commit()

    def grant(
        self,
        workspace_id: str,
        step: UsageStep,
        amount: int,
        *,
        by: str,
        expires_at: datetime | None = None,
        note: str = "",
        resume_now: bool = True,
    ) -> tuple[Grant, Released]:
        """Give extra credits for a step. With ``resume_now`` whatever waited for them goes on
        straight away, oldest first, as far as the credits reach."""
        if amount < 1:
            raise InvalidInput("give at least one credit")
        now = self._now()
        if expires_at is not None and expires_at <= now:
            raise InvalidInput("the credits would already have expired")
        with self._platform() as p:
            if p.workspaces.get(workspace_id) is None:
                raise NotFound(f"workspace {workspace_id}")
            made = p.plans.add_grant(
                workspace_id, step, amount, expires_at=expires_at, note=note, granted_by=by
            )
            p.audit.record(
                "credits_granted", actor_user_id=by, workspace_id=workspace_id,
                target_type="grant", target_id=made.id, note=note or None,
                data={"step": step.value, "amount": amount,
                      "expires_at": expires_at.isoformat() if expires_at else None},
            )  # fmt: skip
            p.commit()
        released = self.resume(workspace_id, by=by, quietly=True) if resume_now else Released()
        return made, released

    def revoke_grant(self, workspace_id: str, grant_id: str, *, by: str) -> None:
        with self._platform() as p:
            revoked = p.plans.revoke_grant(workspace_id, grant_id)
            p.audit.record(
                "grant_revoked", actor_user_id=by, workspace_id=workspace_id,
                target_type="grant", target_id=grant_id,
                data={"step": revoked.step.value, "amount": revoked.amount},
            )  # fmt: skip
            p.commit()

    def resume(self, workspace_id: str, *, by: str, quietly: bool = False) -> Released:
        """Let a customer's waiting work go on, as far as its credits reach."""
        service = ResumeService(
            self._uow, workspace_id, IntakeService(self._uow, workspace_id, None), now=self._now
        )
        released = service.release_all(actor=f"user:{by}", quietly=quietly)
        if released.total:
            with self._platform() as p:
                p.audit.record(
                    "work_resumed", actor_user_id=by, workspace_id=workspace_id,
                    target_type="workspace", target_id=workspace_id,
                    data={"leads": released.leads, "rows": released.rows},
                )  # fmt: skip
                p.commit()
        return released

    def dismiss_request(self, workspace_id: str, *, by: str, note: str = "") -> None:
        with self._platform() as p:
            p.audit.record(
                "credits_dismissed", actor_user_id=by, workspace_id=workspace_id,
                target_type="workspace", target_id=workspace_id, note=note or None,
            )  # fmt: skip
            p.commit()

    # ------------------------------------------------------------------ people

    def users(self, search: str = "") -> list[UserRow]:
        needle = search.strip().lower()
        with self._platform() as p:
            names = {w.id: w.name for w in p.workspaces.all()}
        found = []
        with self._identity() as ids:
            for user in ids.users.all():
                if needle and needle not in user.email and needle not in user.name.lower():
                    continue
                places = [
                    (names.get(m.workspace_id, "?"), m.role.value)
                    for m in ids.memberships.for_user(user.id)
                ]
                found.append(UserRow(user, places))
        return found

    def set_user_status(self, user_id: str, status: UserStatus, *, by: str) -> None:
        with self._identity() as ids:
            ids.users.set_status(user_id, status)
            if status is UserStatus.DISABLED:
                ids.sessions.revoke_for_user(user_id)
            ids.audit.record(
                "user_enabled" if status is UserStatus.ACTIVE else "user_disabled",
                actor_user_id=by, target_type="user", target_id=user_id,
            )  # fmt: skip
            ids.commit()

    def sign_out_everywhere(self, user_id: str, *, by: str) -> int:
        with self._identity() as ids:
            count = ids.sessions.revoke_for_user(user_id)
            ids.audit.record(
                "sessions_revoked_by_admin", actor_user_id=by, target_type="user",
                target_id=user_id, data={"n": count},
            )  # fmt: skip
            ids.commit()
        return count

    def set_platform_role(self, user_id: str, role: PlatformRole | None, *, by: str) -> None:
        """Make someone platform staff or take it away. The caller checks the actor is a
        superadmin; the last superadmin cannot be removed."""
        with self._identity() as ids:
            target = ids.users.get(user_id)
            if target.platform_role is SUPER and role is not SUPER:
                supers = [u for u in ids.users.all() if u.platform_role is SUPER]
                if len(supers) <= 1:
                    raise AdminError(
                        409, "last_superadmin", "There must be at least one superadmin."
                    )
            ids.users.set_platform_role(user_id, role)
            if role is None:
                ids.sessions.revoke_for_user(user_id)  # staff sessions end with the role
            ids.audit.record(
                "platform_role_set", actor_user_id=by, target_type="user", target_id=user_id,
                data={"role": role.value if role else None},
            )  # fmt: skip
            ids.commit()

    # ------------------------------------------------------------------ plans and settings

    def settings(self) -> tuple[PlatformSettings, int]:
        with self._platform() as p:
            return p.settings.get()

    def plan_customers(self) -> dict[str, int]:
        """How many customers are on each plan."""
        counts: dict[str, int] = {}
        with self._platform() as p:
            for workspace in p.workspaces.all():
                found = p.plans.assignment(workspace.id)
                code = found.plan_code if found else UNLIMITED.code
                counts[code] = counts.get(code, 0) + 1
        return counts

    def save_plan(self, plan: Plan, *, by: str, version: int) -> int:
        if not plan.code.replace("-", "").replace("_", "").isalnum() or plan.code == UNLIMITED.code:
            raise InvalidInput("a plan code is letters, digits, - and _ (and not 'unlimited')")
        with self._platform() as p:
            current, _ = p.settings.get()
            plans = {**current.plans, plan.code: plan}
            saved = p.settings.save(replace(current, plans=plans), expected_version=version)
            p.audit.record(
                "plan_saved", actor_user_id=by, target_type="plan", target_id=plan.code,
                data={"limits": {s.value: v for s, v in plan.limits.items()}},
            )  # fmt: skip
            p.commit()
        return saved

    def set_default_plan(self, code: str, *, by: str, version: int) -> int:
        with self._platform() as p:
            current, _ = p.settings.get()
            if code not in current.plans:
                raise AdminError(422, "unknown_plan", f"There is no plan {code!r}.")
            saved = p.settings.save(replace(current, default_plan=code), expected_version=version)
            p.audit.record(
                "default_plan_set", actor_user_id=by, target_type="plan", target_id=code
            )  # fmt: skip
            p.commit()
        return saved

    def update_settings(
        self, *, by: str, version: int, changes: dict[str, Any]
    ) -> tuple[PlatformSettings, int]:
        allowed = {"kill_runs", "kill_drafts", "superadmin_enabled", "announcement"}
        if set(changes) - allowed:
            raise InvalidInput(f"cannot change {sorted(set(changes) - allowed)}")
        with self._platform() as p:
            current, _ = p.settings.get()
            updated = replace(current, **changes)
            saved = p.settings.save(updated, expected_version=version)
            p.audit.record(
                "platform_settings_changed", actor_user_id=by,
                data={k: v for k, v in changes.items() if k != "announcement"}
                | ({"announcement": "set" if changes.get("announcement") else "cleared"}
                   if "announcement" in changes else {}),
            )  # fmt: skip
            p.commit()
        return updated, saved

    def key_refusals(self, since: datetime) -> dict[str, int]:
        """Calls each vendor refused our key for since ``since``; the model under its own name."""
        from outbound.domain.vendors import BY_CODE

        with self._platform() as p:
            found = p.figures.key_failures(since)
        out = {code: n for code, n in found.items() if code in BY_CODE}
        refused_llm = sum(n for name, n in found.items() if name not in BY_CODE)
        if refused_llm:
            out["llm"] = refused_llm
        return out

    def force_reconnect(self, workspace_id: str, mailbox_id: str, *, by: str) -> None:
        """Make a customer connect a mailbox again (a leaked or suspect token): its credentials
        stay, but nothing is drafted through it until the customer signs in to it again."""
        from outbound.domain.enums import MailboxStatus
        from outbound.stages.mailboxes import mark

        with self._uow(workspace_id) as uow:
            if not any(m.id == mailbox_id for m in uow.mailboxes.all()):
                raise NotFound(f"mailbox {mailbox_id}")
        mark(self._uow, workspace_id, mailbox_id, MailboxStatus.NEEDS_RECONNECT)
        with self._platform() as p:
            p.audit.record(
                "mailbox_reconnect_forced", actor_user_id=by, workspace_id=workspace_id,
                target_type="mailbox", target_id=mailbox_id,
            )  # fmt: skip
            p.commit()

    # ------------------------------------------------------------------ audit

    def audit(
        self,
        *,
        workspace_id: str | None = None,
        actor_user_id: str | None = None,
        action: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        with self._platform() as p:
            rows = p.audit.recent(
                workspace_id=workspace_id, actor_user_id=actor_user_id, action=action,
                since=since, until=until, limit=limit,
            )  # fmt: skip
            names = {w.id: w.name for w in p.workspaces.all()}
        with self._identity() as ids:
            emails = {u.id: u.email for u in ids.users.all()}
        return [
            {**r, "workspace": names.get(r["workspace_id"] or "", ""),
             "actor": emails.get(r["actor_user_id"] or "", "")}
            for r in rows
        ]  # fmt: skip

    def audit_csv(self, **filters: Any) -> str:
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["time", "who", "customer", "action", "target", "note", "details"])
        for r in self.audit(limit=5000, **filters):
            writer.writerow(
                [
                    r["at"].isoformat(), r["actor"], r["workspace"], r["action"],
                    f"{r['target_type'] or ''} {r['target_id'] or ''}".strip(),
                    _csv_safe(r["note"] or ""), _csv_safe(str(r["data"])),
                ]
            )  # fmt: skip
        return out.getvalue()

    # ------------------------------------------------------------------ building the rows

    def _rows(
        self, p: PlatformUnitOfWork, settings: PlatformSettings, now: datetime
    ) -> list[CustomerRow]:
        month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = (month + timedelta(days=32)).replace(day=1)
        figures = p.figures
        spend, waiting = figures.spend(month, month_end), figures.waiting_leads()
        mailboxes, active = figures.mailboxes(), figures.last_activity()
        leads = figures.lead_counts()
        with self._identity() as ids:
            members = {w.id: len(ids.memberships.members(w.id)) for w in p.workspaces.all()}
            requested = _open_requests(ids.audit.recent(limit=1000))
        rows = []
        for workspace in p.workspaces.all():
            assignment = p.plans.assignment(workspace.id) or PlanAssignment(
                UNLIMITED.code, workspace.created_at or now, None
            )
            plan = settings.plan(assignment.plan_code)
            start, end = period_bounds(assignment.started_at, now)
            quota = compute_quota(
                assignment, plan, p.plans.overrides(workspace.id), p.plans.grants(workspace.id),
                p.plans.used(workspace.id, start, end), workspace.status, now,
            )  # fmt: skip
            total, bad = mailboxes.get(workspace.id, (0, 0))
            rows.append(
                CustomerRow(
                    workspace,
                    plan,
                    quota,
                    spend.get(workspace.id, 0),
                    leads.get(workspace.id, 0),
                    members.get(workspace.id, 0),
                    total,
                    bad,
                    waiting.get(workspace.id, 0),
                    active.get(workspace.id),
                    workspace.id in requested,
                )
            )
        return rows


def _open_requests(entries: list[dict[str, Any]]) -> set[str]:
    """Workspaces whose latest 'asked for credits' is newer than any answer to it. ``entries``
    are newest first."""
    open_for: set[str] = set()
    answered: set[str] = set()
    for entry in entries:
        ws = entry["workspace_id"]
        if not ws:
            continue
        if entry["action"] in ANSWERED:
            answered.add(ws)
        elif entry["action"] == "credits_requested" and ws not in answered:
            open_for.add(ws)
    return open_for


def _csv_safe(text: str) -> str:
    """A spreadsheet runs a cell that starts with = + - or @ as a formula; make it plain text."""
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


__all__ = ["AccessLevel", "AdminError", "AdminService", "StepQuota"]
