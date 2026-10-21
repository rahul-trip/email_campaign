import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Callout, Field, Problem, Select, Textarea } from "./ui";

type Company = Schemas["CompanyOut"];
export type PolicyStage = Schemas["PolicySkipIn"]["from_stage"];

/** The stages that check the country rule, in pipeline order, in the words the screens use. */
export const POLICY_STAGES: [PolicyStage, string][] = [
  ["gate", "Qualify"],
  ["contacts", "Find people"],
  ["email", "Find the email address"],
  ["copy", "Write the email"],
  ["deliver", "Draft it in the mailbox"],
];
const LABEL = Object.fromEntries(POLICY_STAGES) as Record<PolicyStage, string>;

/** The journey's stage keys that run a country check. */
export const JOURNEY_POLICY_STAGE: Record<string, PolicyStage> = {
  qualification: "gate",
  people: "contacts",
  email: "email",
  copy: "copy",
  outreach: "deliver",
};

const FINISHED = new Set(["in_sequence", "replied", "completed", "rejected", "suppressed"]);

/**
 * Skip the country rule for one lead from a stage onward, or revoke the skip. A lead stopped by
 * the rule can only skip from the stage that stopped it or an earlier one; the server checks too.
 */
export function PolicySkip({ company, heldAt, preset }: { company: Company; heldAt?: string | null; preset?: PolicyStage }) {
  const queryClient = useQueryClient();
  const refresh = () => {
    for (const key of ["lead", "journey", "timeline", "companies", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  const stoppedAt = (heldAt ?? (company.status === "disqualified" && (company.policy_decision as { outcome?: string } | null)?.outcome === "block" ? "gate" : null)) as PolicyStage | null;
  const choices = stoppedAt ? POLICY_STAGES.slice(0, POLICY_STAGES.findIndex(([s]) => s === stoppedAt) + 1) : POLICY_STAGES;
  const [stage, setStage] = useState<PolicyStage>(preset && choices.some(([s]) => s === preset) ? preset : (stoppedAt ?? "gate"));
  const [reason, setReason] = useState("");
  const skip = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/policy-skip", { params: { path: { company_id: company.id } }, body: { from_stage: stage, reason: reason.trim() } })),
    onSuccess: () => {
      setReason("");
      refresh();
    },
  });
  const revoke = useMutation({
    mutationFn: () => ok(client.DELETE("/api/companies/{company_id}/policy-skip", { params: { path: { company_id: company.id } } })),
    onSuccess: refresh,
  });

  if (company.policy_skip_from) {
    const from = company.policy_skip_from as PolicyStage;
    return (
      <div className="space-y-2">
        <Callout tone="attention" title={`Country rule skipped from "${LABEL[from] ?? from}" on`}>
          You chose to write to this lead without its country's rule. The do-not-contact list still applies, and approving the email asks you to confirm. The timeline says who skipped it and why.
        </Callout>
        {!FINISHED.has(company.status) && company.status !== "approved" && (
          <Button size="sm" variant="secondary" busy={revoke.isPending} onClick={() => revoke.mutate()}>
            Apply the country rule again
          </Button>
        )}
        <Problem error={revoke.error} />
      </div>
    );
  }
  if (FINISHED.has(company.status)) return <p className="text-xs text-muted">Nothing is left to check for this lead.</p>;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted">
        {stoppedAt
          ? `The country rule stopped this lead at "${LABEL[stoppedAt]}". Skip it from there (or earlier) and the lead goes straight on.`
          : "Skip the country rule for this lead from a step onward. The do-not-contact list always applies."}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Skip from this step on">
          <Select value={stage} onChange={(e) => setStage(e.target.value as PolicyStage)}>
            {choices.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Why" hint="Kept with the record, with your name.">
          <Textarea rows={2} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: they asked us to send details" />
        </Field>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button size="sm" variant="secondary" busy={skip.isPending} disabled={!reason.trim()} onClick={() => skip.mutate()}>
          Skip the country rule
        </Button>
        <Problem error={skip.error} />
      </div>
    </div>
  );
}
