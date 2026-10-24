/** Settings → Plan & usage: what the plan allows, what is used, and asking for more. */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../api/client";
import { isViewing, useCurrent } from "../app/session";
import { Button, Callout, Card, Dialog, Field, Problem, QueryState, SaveNote, Select, Table, Td, Textarea, Th } from "../components/ui";
import { cx } from "../lib/cx";
import { STEP_LABEL, day, shown, useUsage, waitingTotal, type Usage } from "../lib/usage";

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
        subtitle={`Allowances renew on ${day(usage.period_end)}.${usage.access_until ? ` Access until ${day(usage.access_until)}.` : ""}`}
        actions={
          !isViewing(workspace) && (
            <Button variant="secondary" size="sm" onClick={() => setAsking(true)}>
              Ask for more credits
            </Button>
          )
        }
      >
        <Table>
          <thead>
            <tr>
              <Th>What</Th>
              <Th>Used</Th>
              <Th>Allowance</Th>
              <Th>Extra credits</Th>
              <Th>Left</Th>
            </tr>
          </thead>
          <tbody>
            {shown(usage).map((s) => (
              <tr key={s.step}>
                <Td className="font-medium">{STEP_LABEL[s.step] ?? s.step}</Td>
                <Td>{s.used}</Td>
                <Td>{s.limit ?? "No limit"}</Td>
                <Td>{s.granted ? `+${s.granted}` : "—"}</Td>
                <Td>
                  <Meter used={s.used} total={s.limit === null ? null : s.limit + s.granted} />
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
        <p className="mt-3 text-xs text-muted">Each step is counted once per lead: researching a lead again, retrying or rerunning costs nothing more.</p>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Also in your plan">
          <dl className="space-y-1.5 text-[13px]">
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
                <Th>Step</Th>
                <Th>Credits</Th>
                <Th>Given</Th>
                <Th>Until</Th>
                <Th>Note</Th>
              </tr>
            </thead>
            <tbody>
              {usage.grants.map((g) => (
                <tr key={g.id} className={cx(g.revoked_at && "text-muted line-through")}>
                  <Td>{STEP_LABEL[g.step] ?? g.step}</Td>
                  <Td>+{g.amount}</Td>
                  <Td>{day(g.created_at)}</Td>
                  <Td>{g.expires_at ? day(g.expires_at) : "No end"}</Td>
                  <Td className="text-muted">{g.note}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}
      {asking && <AskDialog usage={usage} onClose={() => setAsking(false)} />}
    </div>
  );
}

const Line = ({ label, value }: { label: string; value: number | null }) => (
  <div className="flex justify-between gap-3">
    <dt className="text-muted">{label}</dt>
    <dd className="font-medium">{value ?? "No limit"}</dd>
  </div>
);

function Meter({ used, total }: { used: number; total: number | null }) {
  if (total === null) return <span className="text-muted">No limit</span>;
  const left = Math.max(0, total - used);
  const share = total === 0 ? 1 : Math.min(1, used / total);
  return (
    <div className="flex items-center gap-2" role="meter" aria-valuemin={0} aria-valuemax={total} aria-valuenow={Math.min(used, total)} aria-label={`${left} left`}>
      <div className="h-1.5 w-24 overflow-hidden rounded-full bg-surface-container">
        <div className={cx("h-full rounded-full", share >= 1 ? "bg-error" : share >= 0.8 ? "bg-attention" : "bg-primary-container")} style={{ width: `${share * 100}%` }} />
      </div>
      <span className={cx("font-mono text-xs", left === 0 && "font-semibold text-error")}>{left}</span>
    </div>
  );
}

function Waiting({ usage }: { usage: Usage }) {
  const total = waitingTotal(usage);
  return (
    <Card title="Waiting for credits" subtitle={total ? "These continue by themselves as soon as credits exist." : undefined}>
      {total === 0 ? (
        <p className="text-[13px] text-muted">Nothing is waiting.</p>
      ) : (
        <ul className="space-y-1 text-[13px]">
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

function AskDialog({ usage, onClose }: { usage: Usage; onClose: () => void }) {
  const [step, setStep] = useState("");
  const [note, setNote] = useState("");
  const ask = useMutation({
    mutationFn: () => ok(client.POST("/api/usage/request-credits", { body: { step: (step || null) as "manual" | null, note } })),
  });
  return (
    <Dialog
      title="Ask for more credits"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {ask.isSuccess ? "Close" : "Cancel"}
          </Button>
          {!ask.isSuccess && (
            <Button busy={ask.isPending} disabled={!step && !note.trim()} onClick={() => ask.mutate()}>
              Send request
            </Button>
          )}
        </>
      }
    >
      <p className="text-xs text-muted">The team who runs this service sees your request and can add credits or extend your access.</p>
      <Field label="What do you need more of?">
        <Select value={step} onChange={(e) => setStep(e.target.value)}>
          <option value="">Not sure</option>
          {usage.steps.map((s) => (
            <option key={s.step} value={s.step}>
              {STEP_LABEL[s.step] ?? s.step}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Anything we should know?" hint="For example how many more you need, or why.">
        <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} className="w-full" />
      </Field>
      <Problem error={ask.error} />
      <SaveNote mutation={ask} done="Sent. The team will get back to you." />
    </Dialog>
  );
}
