import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { words } from "../lib/format";
import { Button, Confirm, Field, Problem, Textarea } from "./ui";

type Email = Schemas["EmailOut"];

const PROVEN = new Set(["valid", "catch_all_resolved"]);
const refreshKeys = ["lead", "journey", "timeline", "waterfall", "companies", "status", "review"];

/**
 * Write to an address whatever the verifier said (even "invalid"), or let it be checked again.
 * Approving an email to it then asks the operator to confirm the skip.
 */
export function SkipCheck({ email, personName }: { email: Email; personName?: string | null }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const path = { params: { path: { email_id: email.id } } };
  const refresh = () => {
    for (const key of refreshKeys) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  const skip = useMutation({
    mutationFn: () => ok(client.POST("/api/contact-emails/{email_id}/skip-verification", { ...path, body: { reason: reason.trim() } })),
    onSuccess: () => {
      setOpen(false);
      setReason("");
      refresh();
    },
  });
  const restore = useMutation({
    mutationFn: () => ok(client.DELETE("/api/contact-emails/{email_id}/skip-verification", path)),
    onSuccess: refresh,
  });

  if (!email.email) return null;
  if (email.verification_skipped) {
    return (
      <span className="inline-flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-attention-container px-2 py-0.5 text-[11px] font-medium text-on-attention-container">Check skipped by you</span>
        <Button size="sm" variant="ghost" busy={restore.isPending} onClick={() => restore.mutate()}>
          Check it again
        </Button>
        <Problem error={restore.error} />
      </span>
    );
  }
  if (PROVEN.has(email.status)) return null;
  return (
    <>
      <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
        Skip the check
      </Button>
      {open && (
        <Confirm
          title={`Write to ${email.email} without proof?`}
          confirmLabel="Skip the check"
          busy={skip.isPending}
          error={skip.error}
          onClose={() => setOpen(false)}
          onConfirm={() => reason.trim() && skip.mutate()}
        >
          <p>
            The check said <strong>{words(email.status)}</strong>. If you know this address works{personName ? ` for ${personName}` : ""}, the lead goes on with it: no more checks are paid for, it becomes the address written to, and approving the email asks you to confirm.
          </p>
          {email.status === "invalid" && <p className="mt-2 font-medium">An address the check called invalid will probably bounce, and bounces hurt your sending domain.</p>}
          <p className="mt-2">The do-not-contact list still applies.</p>
          <div className="mt-3">
            <Field label="Why" hint="Kept with the record, with your name.">
              <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: I have written to them at this address before" />
            </Field>
          </div>
          {!reason.trim() && <p className="mt-1 text-[11px] text-muted">Say why before you confirm.</p>}
        </Confirm>
      )}
    </>
  );
}
