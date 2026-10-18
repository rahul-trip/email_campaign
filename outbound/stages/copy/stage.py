"""Stage 6: write touch 1 for the best contact and move the company to ``copy_ready``."""

from __future__ import annotations

from outbound.db.uow import UnitOfWork
from outbound.domain.entities import Contact, ContactEmail
from outbound.domain.enums import CompanyStatus, ContactStatus, MessageState
from outbound.domain.footer import MissingProfileField, render_footer
from outbound.domain.policies import is_safe_email_status
from outbound.providers.ports import LlmClient
from outbound.stages.base import StageContext, StageFailure, StageResult
from outbound.stages.copy.graph import CopyInput, CopyOutput, run_copy
from outbound.stages.policy import policy_decision_for

_USABLE = (ContactStatus.CANDIDATE, ContactStatus.ACTIVE)


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
            decision = policy_decision_for(uow, company)
            notes = "\n".join(n.body for n in uow.notes.for_company(company.id))
            shots = (
                uow.messages.edited_examples(company.campaign_id, wanted)
                if company.campaign_id and wanted
                else []
            )
            return chosen, decision, notes, shots

        chosen, decision, notes, shots = ctx.read(load)
        if chosen is None:
            raise StageFailure("no contact has an address that is safe to send to")
        contact, address = chosen

        footer: str | None = None
        if decision.footer_template:
            try:
                footer = render_footer(decision.footer_template, sender, address.provenance)
            except MissingProfileField as error:
                raise StageFailure(str(error)) from None

        output = run_copy(
            self._llm,
            CopyInput(
                sender=sender,
                first_name=contact.first_name or (contact.full_name or "there").split()[0],
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
        if contact.status not in _USABLE:
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
