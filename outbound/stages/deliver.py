"""Stage 8: save an approved email as a draft in the operator's mailbox.

Everything is checked again first, because time has passed since the operator approved it: the
address may have been suppressed, the policy edited, the contact opted out. A draft that fails
the safe-to-send rule is never saved; the lead stays approved and is looked at again later.

Saving is idempotent. The draft gets a Message-ID derived from the message, and the mailbox is
asked whether it already has that draft, so a crash between "saved" and "recorded" cannot leave
a duplicate.
"""

from __future__ import annotations

from outbound.db.uow import UnitOfWork
from outbound.domain.entities import Message
from outbound.domain.enums import CompanyStatus, HoldReason, MessageState
from outbound.domain.policies import check_send
from outbound.providers.ports import Mailbox, OutgoingDraft
from outbound.stages.base import StageContext, StageFailure, StageResult
from outbound.stages.policy import policy_decision_for


def draft_message_id(message: Message, mailbox_address: str) -> str:
    return f"<{message.id}.outbound@{mailbox_address.rpartition('@')[2]}>"


class DeliverStage:
    name = "deliver"  # cannot fail a lead: a mailbox error leaves it approved and retries
    input_status = CompanyStatus.APPROVED
    guard_policy = True
    spends = False

    def __init__(self, mailbox: Mailbox) -> None:
        self._mailbox = mailbox

    def handle(self, ctx: StageContext) -> StageResult:
        company = ctx.company
        safe_only = bool(ctx.workspace.settings.get("safe_to_send_only", True))

        def load(uow: UnitOfWork):  # type: ignore[no-untyped-def]
            approved = [
                m
                for m in uow.messages.for_company(company.id)
                if m.state is MessageState.APPROVED and m.step == 0
            ]
            if not approved:
                return None
            message = approved[0]
            contact = uow.contacts.get(message.contact_id)
            address = uow.emails.get(message.contact_email_id)
            decision = policy_decision_for(uow, company, email_provenance=address.provenance)
            verdict = check_send(
                email_status=address.status,
                contact_status=contact.status,
                email_suppressed=bool(address.email)
                and uow.suppressions.is_email_suppressed(address.email or ""),
                domain_suppressed=uow.suppressions.is_domain_suppressed(company.domain),
                policy_decision=decision,
                safe_to_send_only=safe_only,
            )
            return message, address, verdict, decision.hold_reason

        loaded = ctx.read(load)
        if loaded is None:
            raise StageFailure("the company is approved but has no approved message")
        message, address, verdict, hold_reason = loaded
        if not verdict.ok or not address.email:
            # The lead was fine when approved and is not now (an opt-out, a bounce, a changed
            # rule). Never draft it; hold it with the reason, and withdraw the approved email.
            reasons = "; ".join(verdict.reasons or ("no address",))
            return StageResult(
                CompanyStatus.HELD,
                reason=f"not safe to send: {reasons}",
                hold_reason=hold_reason or HoldReason.NEEDS_OPERATOR,
                write=lambda uow: _withdraw(uow, message),
            )

        remote_id = draft_message_id(message, self._mailbox.address)
        if not self._mailbox.draft_exists(remote_id):
            self._mailbox.append_draft(
                OutgoingDraft(
                    to_address=address.email,
                    subject=message.subject,
                    body=message.final_body or message.generated_body,
                    message_id=remote_id,
                )
            )

        def write(uow: UnitOfWork) -> None:
            uow.messages.transition(
                message.id,
                MessageState.DRAFTED,
                expected_version=message.row_version,
                set_fields={"remote_draft_id": remote_id},
            )

        return StageResult(
            CompanyStatus.IN_SEQUENCE,
            reason="draft saved",
            write=write,
            undo=lambda: _ignore(self._mailbox.delete_draft(remote_id)),
        )


def _ignore(_: object) -> None:
    """Adapts ``delete_draft`` (which reports a count) to the ``undo`` hook."""


def _withdraw(uow: UnitOfWork, message: Message) -> None:
    uow.messages.transition(
        message.id, MessageState.CANCELLED, expected_version=message.row_version
    )
