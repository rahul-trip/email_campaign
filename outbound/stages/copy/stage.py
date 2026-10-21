"""Stage 6: write touch 1 for the best contact and move the company to ``copy_ready``."""

from __future__ import annotations

from outbound.db.uow import UnitOfWork
from outbound.domain.entities import Contact, ContactEmail
from outbound.domain.enums import (
    WORKABLE_CONTACT_STATUSES,
    CompanyStatus,
    HoldReason,
    MessageState,
)
from outbound.domain.footer import DEFAULT_FOOTER, MissingProfileField, render_footer
from outbound.domain.policies import PolicyOutcome, is_safe_email_status
from outbound.providers.ports import LlmClient
from outbound.stages.base import StageContext, StageFailure, StageResult
from outbound.stages.copy.graph import CopyInput, CopyOutput, run_copy
from outbound.stages.policy import policy_decision_for


class CopyStage:
    name = "copy"
    input_status = CompanyStatus.EMAIL_READY
    guard_policy = True
    spends = True

    def __init__(self, llm: LlmClient, *, examples: int | None = None) -> None:
        self._llm = llm
        self._examples = examples

    def handle(self, ctx: StageContext) -> StageResult:
        company = ctx.company
        sender = dict(ctx.workspace.sender_profile)
        safe_only = bool(ctx.workspace.settings.get("safe_to_send_only", True))
        wanted = (
            self._examples
            if self._examples is not None
            else int(ctx.workspace.settings.get("few_shot_examples", 5))
        )
        if not sender.get("reviewed_at"):
            raise StageFailure(
                "review and save your sender profile first (Settings → Sender profile, or "
                "`outbound sender-profile review`): its statements are quoted in every email"
            )
        for field_name in ("signature_name", "signature_title"):
            value = str(sender.get(field_name) or "").strip()
            if not value or value.startswith("["):
                raise StageFailure(f"the sender profile needs {field_name}")

        def load(uow: UnitOfWork):  # type: ignore[no-untyped-def]
            chosen = _chosen_address(uow, company.id, safe_only)
            decision = (
                policy_decision_for(
                    uow,
                    company,
                    stage=self.name,
                    email_provenance=chosen[1].provenance,
                    recipient_id=chosen[0].id,
                )
                if chosen
                else None
            )
            notes = "\n".join(n.body for n in uow.notes.for_company(company.id))
            shots = (
                uow.messages.edited_examples(company.campaign_id, wanted)
                if company.campaign_id and wanted
                else []
            )
            return chosen, decision, notes, shots

        chosen, decision, notes, shots = ctx.read(load)
        if chosen is None or decision is None:
            raise StageFailure("no contact has an address that is safe to send to")
        contact, address = chosen
        if decision.outcome is not PolicyOutcome.ALLOW:  # e.g. the consent is someone else's
            return StageResult(
                CompanyStatus.HELD,
                reason="; ".join(decision.reasons),
                hold_reason=decision.hold_reason or HoldReason.NEEDS_OPERATOR,
                company_updates={"policy_decision": decision.to_json()},
            )

        # The footer is its own setting: on by default, and kept when the country rule is
        # skipped. A country without a footer of its own gets the short default one.
        footer: str | None = None
        if ctx.workspace.settings.get("footer_enabled", True):
            template = decision.footer_template or DEFAULT_FOOTER
            try:
                footer = render_footer(template, sender, address.provenance)
            except MissingProfileField as error:
                raise StageFailure(str(error)) from None

        output = run_copy(
            self._llm,
            CopyInput(
                sender=sender,
                first_name=contact.first_name
                or next(iter((contact.full_name or "").split()), "there"),
                title=contact.title or "",
                company_name=company.name or company.domain,
                research=company.research or {},
                answers={k: str(v) for k, v in (company.research_answers or {}).items()},
                notes=notes,
                examples=tuple(
                    (m.generated_body, m.final_body) for m in shots if m.final_body is not None
                ),
                footer=footer,
            ),
        )
        return StageResult(
            CompanyStatus.COPY_READY,
            reason=_summary(output),
            write=lambda uow: _save(uow, company.id, contact, address, output),
        )


def _chosen_address(
    uow: UnitOfWork, company_id: str, safe_only: bool
) -> tuple[Contact, ContactEmail] | None:
    for contact in uow.contacts.for_company(company_id):
        if contact.status not in WORKABLE_CONTACT_STATUSES:
            continue
        for address in uow.emails.for_contact(contact.id):
            if address.is_primary and is_safe_email_status(
                address.status, safe_to_send_only=safe_only
            ):
                return contact, address
    return None


def _summary(output: CopyOutput) -> str:
    flag = (
        f", flagged: {', '.join(i.rule for i in output.report.issues)}"
        if output.report.flagged
        else ""
    )
    return f"written in {output.attempts} attempt(s){flag}"


def _save(
    uow: UnitOfWork, company_id: str, contact: Contact, address: ContactEmail, output: CopyOutput
) -> None:
    uow.messages.create(
        company_id=company_id,
        contact_id=contact.id,
        contact_email_id=address.id,
        step=0,
        subject=output.subject,
        generated_body=output.body,
        state=MessageState.GENERATED,
        snippets=output.snippets,
        lint_report=output.report.to_json(),
    )
