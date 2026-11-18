/** Settings → Plan & usage: the plan's AI credits, what is used, and asking for more. */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../api/client";
import { isViewing, useCurrent } from "../app/session";
import { Button, Callout, Card, Dialog, Field, Input, Problem, QueryState, SaveNote, Table, Td, Textarea, Th } from "../ui/compat";
import { cx } from "../lib/cx";
import { credits, wholeCredits } from "../lib/format";
import { STEP_LABEL, creditState, day, useUsage, waitingTotal, type Usage } from "../lib/usage";

export function PlanAndUsage() {
  const usage = useUsage();
  return <QueryState query={usage}>{(data) => <Plan usage={data} />}</QueryState>;
}

function Plan({ usage }: { usage: Usage }) {
  const { workspace } = useCurrent();
  const [asking, setAsking] = useState(false);
  const reopen = usage.access === "read_only";
  return (
    <div className="space-y-4">
      {usage.announcement && <Callout tone="info">{usage.announcement}</Callout>}
      {reopen && (
        <Callout tone="error" title="Access to this workspace has ended">
          It is read-only: everything is kept, and nothing can be added or run until your access is extended. Ask below.
        </Callout>
      )}
      <Card
        tour="plan-meters"
        title={`${usage.plan_name} plan`}
        subtitle={`AI credits renew on ${day(usage.period_end)}.${usage.access_until ? ` Access until ${day(usage.access_until)}.` : ""}`}
        actions={
          !isViewing(workspace) && (
            <Button variant="secondary" size="sm" onClick={() => setAsking(true)}>
              Ask for more AI credits
            </Button>
          )
        }
      >
        <dl className="grid gap-3 sm:grid-cols-4">
          <Figure label="Each month" value={wholeCredits(usage.credits.monthly)} />
          <Figure label="Extra given" value={usage.credits.granted ? `+${wholeCredits(usage.credits.granted)}` : "—"} />
          <Figure label="Used" value={credits(usage.credits.used_milli)} />
          <Figure label="Left" value={usage.credits.remaining_milli == null ? "No limit" : credits(usage.credits.remaining_milli)} />
        </dl>
        <div className="mt-3">
          <Meter usage={usage} />
        </div>
        <p className="mt-3 text-small text-muted">
          Every search, email lookup, verification and AI model call uses AI credits; answers reused from earlier cost nothing. A step that has started finishes even if it takes you a little past your allowance.
        </p>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Also in your plan">
          <dl className="space-y-1.5 text-body">
            <Line label="People" value={usage.seats} />
            <Line label="Mailboxes" value={usage.mailboxes} />
            <Line label="Active campaigns" value={usage.active_campaigns} />
          </dl>
        </Card>
        <Waiting usage={usage} />
      </div>

      {usage.grants.length > 0 && (
        <Card title="Extra credits you were given">
          <Table>
            <thead>
              <tr>
                <Th>AI credits</Th>
                <Th>Given</Th>
                <Th>Until</Th>
                <Th>Note</Th>
              </tr>
            </thead>
            <tbody>
              {usage.grants.map((g) => (
                <tr key={g.id} className={cx(g.revoked_at && "text-muted line-through")}>
                  <Td>+{wholeCredits(g.amount)}</Td>
                  <Td>{day(g.created_at)}</Td>
                  <Td>{g.expires_at ? day(g.expires_at) : "No end"}</Td>
                  <Td className="text-muted">{g.note}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
      {asking && <AskDialog onClose={() => setAsking(false)} />}
    </div>
  );
}

const Line = ({ label, value }: { label: string; value: number | null }) => (
  <div className="flex justify-between gap-3">
    <dt className="text-muted">{label}</dt>
    <dd className="font-medium">{value ?? "No limit"}</dd>
  </div>
);

const Figure = ({ label, value }: { label: string; value: string }) => (
  <div>
    <dt className="text-small text-muted">{label}</dt>
    <dd className="tnum text-title font-semibold">{value}</dd>
  </div>
);

function Meter({ usage }: { usage: Usage }) {
  const state = creditState(usage);
  if (state === null) return <span className="text-small text-muted">No limit on AI credits</span>;
  const share = Math.min(1, state.share);
  return (
    <div
      className="flex items-center gap-3"
      role="meter"
      aria-valuemin={0}
      aria-valuemax={state.allowance}
      aria-valuenow={Math.min(state.used, state.allowance)}
      aria-label={`${Math.round(share * 100)}% of AI credits used`}
    >
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface-3">
        <div className={cx("h-full rounded-full", share >= 1 ? "bg-error" : share >= 0.8 ? "bg-attention" : "bg-primary")} style={{ width: `${share * 100}%` }} />
      </div>
      <span className={cx("tnum text-small", state.out && "font-semibold text-error")}>{Math.round(share * 100)}% used</span>
    </div>
  );
}

function Waiting({ usage }: { usage: Usage }) {
  const total = waitingTotal(usage);
  return (
    <Card title="Waiting for AI credits" subtitle={total ? "These continue by themselves as soon as AI credits are back." : undefined}>
      {total === 0 ? (
        <p className="text-body text-muted">Nothing is waiting.</p>
      ) : (
        <ul className="space-y-1 text-body">
          {Object.entries(usage.waiting_leads).map(([step, n]) => (
            <li key={step}>
              {n} lead{n === 1 ? "" : "s"} waiting at <strong>{STEP_LABEL[step] ?? step}</strong>
            </li>
          ))}
          {usage.waiting_rows > 0 && (
            <li>
              {usage.waiting_rows} you added {usage.waiting_rows === 1 ? "is" : "are"} waiting to become leads
            </li>
          )}
        </ul>
      )}
    </Card>
  );
}

function AskDialog({ onClose }: { onClose: () => void }) {
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const wanted = amount.trim() === "" ? null : Math.max(1, Math.round(Number(amount)));
  const ask = useMutation({
    mutationFn: () => ok(client.POST("/api/usage/request-credits", { body: { amount: wanted, note } })),
  });
  return (
    <Dialog
      title="Ask for more AI credits"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {ask.isSuccess ? "Close" : "Cancel"}
          </Button>
          {!ask.isSuccess && (
            <Button busy={ask.isPending} disabled={!wanted && !note.trim()} onClick={() => ask.mutate()}>
              Send request
            </Button>
          )}
        </>
      }
    >
      <p className="text-small text-muted">The team who runs this service sees your request and can add credits or extend your access.</p>
      <Field label="How many AI credits do you need?" hint="Leave it blank if you are not sure.">
        <Input type="number" min={1} step="100" value={amount} onChange={(e) => setAmount(e.target.value)} className="w-40" />
      </Field>
      <Field label="Anything we should know?" hint="For example what you plan to run, or by when.">
        <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} className="w-full" />
      </Field>
      <Problem error={ask.error} />
      <SaveNote mutation={ask} done="Sent. The team will get back to you." />
    </Dialog>
  );
}
