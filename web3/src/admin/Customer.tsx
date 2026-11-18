/** One customer: its plan and use, limits and credits, access and features, people, mailboxes
 * and history. Every change asks for confirmation, takes an optional note, and is audited. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink } from "lucide-react";
import { useState, type ReactNode } from "react";
import { ApiProblem, client, ok, type Schemas } from "../api/client";
import { useMe } from "../app/session";
import { Button, Callout, Card, Checkbox, Confirm, Dialog, Field, Input, Menu, PageHeader, Problem, QueryState, Select, Table, Tabs, Td, Textarea, Th } from "../ui/compat";
import { credits, usd, wholeCredits } from "../lib/format";
import { AccessPill, Pill, UseBar, When, stepName } from "./bits";
import { A, useId } from "./nav";

type Detail = Schemas["CustomerDetailOut"];
type Tab = "overview" | "limits" | "access" | "members" | "mailboxes" | "activity";

export function CustomerPage() {
  const id = useId();
  const [tab, setTab] = useState<Tab>("overview");
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ["admin", "customer", id], queryFn: () => ok(client.GET("/api/admin/customers/{workspace_id}", { params: { path: { workspace_id: id } } })) });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["admin"] });
  return (
    <>
      <A to="/customers" className="mb-2 inline-flex items-center gap-1 text-small font-semibold text-muted hover:text-ink">
        <ArrowLeft className="size-3.5" aria-hidden /> Customers
      </A>
      <QueryState query={detail} rows={6}>
        {(d) => (
          <>
            <Header d={d} onChange={refresh} />
            <Tabs
              label="Customer"
              tabs={[
                ["overview", "Overview"],
                ["limits", "Limits and credits"],
                ["access", "Access and features"],
                ["members", `Members (${d.members.length})`],
                ["mailboxes", `Mailboxes (${d.mailboxes.length})`],
                ["activity", "Activity"],
              ]}
              value={tab}
              onChange={setTab}
            >
              {tab === "overview" && <Overview d={d} onChange={refresh} />}
              {tab === "limits" && <Limits d={d} onChange={refresh} />}
              {tab === "access" && <Access d={d} onChange={refresh} />}
              {tab === "members" && <Members d={d} onChange={refresh} />}
              {tab === "mailboxes" && <Mailboxes d={d} onChange={refresh} />}
              {tab === "activity" && <Activity d={d} />}
            </Tabs>
          </>
        )}
      </QueryState>
    </>
  );
}

// ------------------------------------------------------------------ header and actions

type Action = "grant" | "extend" | "plan" | "status" | null;

function Header({ d, onChange }: { d: Detail; onChange: () => void }) {
  const me = useMe();
  const [action, setAction] = useState<Action>(null);
  const [status, setStatus] = useState<"active" | "paused" | "suspended">("paused");
  const row = d.row;
  const close = () => setAction(null);
  const done = () => {
    close();
    onChange();
  };
  return (
    <>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-2">
            {row.name}
            <span className="font-mono text-small font-normal text-muted">{row.slug}</span>
          </span>
        }
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <Pill tone="muted">{row.plan_name}</Pill>
            <AccessPill row={row} />
            <span>
              {row.members} member{row.members === 1 ? "" : "s"} · {row.mailboxes} mailbox{row.mailboxes === 1 ? "" : "es"} · {credits(row.credits_milli)} used this month ({usd(row.cost_micro_usd)} platform cost)
            </span>
          </span>
        }
        actions={
          <div data-tour="admin-customer-actions" className="flex flex-wrap items-center gap-2">
            <Button onClick={() => setAction("grant")}>Grant AI credits</Button>
            <Button variant="secondary" onClick={() => setAction("extend")}>
              Extend access
            </Button>
            {me.data?.user.platform_role === "superadmin" && (
              <a href={`/w/${row.slug}/`} className="inline-flex h-8 items-center gap-1 rounded-lg border border-line-strong px-3 text-body font-semibold hover:bg-surface-2">
                Open workspace <ExternalLink className="size-3.5" aria-hidden />
              </a>
            )}
            <Menu
              label="More actions"
              buttonClassName="inline-flex h-8 items-center rounded-lg border border-line-strong px-3 text-body font-semibold hover:bg-surface-2"
              button={<>More ▾</>}
              items={[
                { label: "Change plan", onSelect: () => setAction("plan") },
                ...(row.status === "active"
                  ? [
                      { label: "Pause the engine", onSelect: () => { setStatus("paused"); setAction("status"); } },
                      { label: "Suspend the customer", tone: "danger" as const, onSelect: () => { setStatus("suspended"); setAction("status"); } },
                    ]
                  : [{ label: "Make it active again", onSelect: () => { setStatus("active"); setAction("status"); } }]),
              ]}
            />
          </div>
        }
      />
      {d.requests.length > 0 && row.open_request && <RequestBanner d={d} onChange={onChange} />}
      {action === "grant" && <GrantDialog d={d} onClose={close} onDone={done} />}
      {action === "extend" && <ExtendDialog d={d} onClose={close} onDone={done} />}
      {action === "plan" && <PlanDialog d={d} onClose={close} onDone={done} />}
      {action === "status" && <StatusDialog d={d} to={status} onClose={close} onDone={done} />}
    </>
  );
}

function RequestBanner({ d, onChange }: { d: Detail; onChange: () => void }) {
  const dismiss = useMutation({
    mutationFn: () => ok(client.POST("/api/admin/customers/{workspace_id}/dismiss-request", { params: { path: { workspace_id: d.row.id } } })),
    onSuccess: onChange,
  });
  const latest = d.requests[0]!;
  return (
    <Callout tone="attention" title="They asked for more AI credits" className="mb-4">
      <span>
        {latest.data.amount ? <strong>{wholeCredits(Number(latest.data.amount))}</strong> : latest.data.step ? <strong>{stepName(String(latest.data.step))}</strong> : "No amount named"}
        {latest.note ? `: “${latest.note}”` : ""} · <When iso={latest.at} time />
      </span>
      <div className="mt-2">
        <Button size="sm" variant="secondary" busy={dismiss.isPending} onClick={() => dismiss.mutate()}>
          Dismiss without granting
        </Button>
      </div>
    </Callout>
  );
}

// ------------------------------------------------------------------ dialogs

function Note({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="Note" hint="Optional. Kept in the audit log.">
      <Textarea rows={2} value={value} onChange={(e) => onChange(e.target.value)} className="w-full" />
    </Field>
  );
}

function GrantDialog({ d, onClose, onDone }: { d: Detail; onClose: () => void; onDone: () => void }) {
  const [amount, setAmount] = useState(500);
  const [expiry, setExpiry] = useState<"period" | "date" | "never">("period");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [resume, setResume] = useState(true);
  const waiting = d.row.waiting;
  const remaining = d.row.credits.remaining_milli;
  const expires = expiry === "period" ? d.row.period_end : expiry === "date" && date ? new Date(`${date}T23:59:59`).toISOString() : null;
  const grant = useMutation({
    mutationFn: () => ok(client.POST("/api/admin/customers/{workspace_id}/grants", { params: { path: { workspace_id: d.row.id } }, body: { amount, expires_at: expires, note, resume_now: resume } })),
  });
  return (
    <Dialog
      title={`Grant AI credits · ${d.row.name}`}
      onClose={() => {
        if (grant.isSuccess) onDone();
        else onClose();
      }}
      footer={
        grant.isSuccess ? (
          <Button onClick={onDone}>Done</Button>
        ) : (
          <>
            <Button variant="secondary" onClick={onClose}>
              Cancel
            </Button>
            <Button busy={grant.isPending} disabled={amount < 1 || (expiry === "date" && !date)} onClick={() => grant.mutate()}>
              Grant {wholeCredits(amount)}
            </Button>
          </>
        )
      }
    >
      {grant.isSuccess ? (
        <p role="status" className="text-body">
          Granted {wholeCredits(amount)}.{" "}
          {grant.data.resumed_leads + grant.data.resumed_rows > 0 ? `${grant.data.resumed_rows} waiting added as leads and ${grant.data.resumed_leads} lead(s) set going.` : "Nothing was waiting."}
        </p>
      ) : (
        <>
          <Field label="AI credits" hint="Added to each month's allowance while the grant lasts.">
            <Input type="number" min={1} step="100" value={amount} onChange={(e) => setAmount(Math.max(0, Math.round(Number(e.target.value))))} className="w-40" />
          </Field>
          <fieldset className="space-y-1 text-body">
            <legend className="mb-1 text-small font-medium">Expires</legend>
            {(
              [
                ["period", `End of this period (${new Date(d.row.period_end).toLocaleDateString()})`],
                ["date", "On a date"],
                ["never", "Never"],
              ] as const
            ).map(([value, label]) => (
              <label key={value} className="flex items-center gap-2">
                <input type="radio" name="expiry" checked={expiry === value} onChange={() => setExpiry(value)} className="accent-[var(--primary)]" />
                {label}
                {value === "date" && expiry === "date" && <Input type="date" aria-label="Expiry date" value={date} onChange={(e) => setDate(e.target.value)} className="ml-1 w-40" />}
              </label>
            ))}
          </fieldset>
          <Note value={note} onChange={setNote} />
          <Checkbox label={`Set waiting work going now${waiting ? ` (${waiting} waiting)` : ""}`} checked={resume} onChange={setResume} />
          {remaining !== null && <p className="text-small text-muted">Left after: {credits(remaining + amount * 1000)} this month.</p>}
          <Problem error={grant.error} />
        </>
      )}
    </Dialog>
  );
}

function ExtendDialog({ d, onClose, onDone }: { d: Detail; onClose: () => void; onDone: () => void }) {
  const [days, setDays] = useState<number | "date">(30);
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const base = Math.max(Date.now(), d.row.access_until ? new Date(d.row.access_until).getTime() : Date.now());
  const preview = days === "date" ? (date ? new Date(`${date}T23:59:59`) : null) : new Date(base + days * 86_400_000);
  const extend = useMutation({
    mutationFn: () =>
      ok(client.POST("/api/admin/customers/{workspace_id}/access", { params: { path: { workspace_id: d.row.id } }, body: days === "date" ? { until: preview?.toISOString(), note } : { days, note } })),
    onSuccess: onDone,
  });
  return (
    <Dialog
      title={`Extend access · ${d.row.name}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={extend.isPending} disabled={!preview} onClick={() => extend.mutate()}>
            Extend
          </Button>
        </>
      }
    >
      {d.row.access === "read_only" && <Callout tone="attention">Access has ended, so the workspace is read-only. Extending reopens it at once and the worker continues where it stopped.</Callout>}
      <Field label="Add">
        <Select value={String(days)} onChange={(e) => setDays(e.target.value === "date" ? "date" : Number(e.target.value))}>
          <option value="7">7 days</option>
          <option value="14">14 days</option>
          <option value="30">30 days</option>
          <option value="90">90 days</option>
          <option value="date">Until a date…</option>
        </Select>
      </Field>
      {days === "date" && (
        <Field label="Until">
          <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-full" />
        </Field>
      )}
      {preview && <p className="text-body">New end: <strong>{preview.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}</strong></p>}
      <Note value={note} onChange={setNote} />
      <Problem error={extend.error} />
    </Dialog>
  );
}

function PlanDialog({ d, onClose, onDone }: { d: Detail; onClose: () => void; onDone: () => void }) {
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: () => ok(client.GET("/api/admin/plans")) });
  const [plan, setPlan] = useState(d.row.plan_code);
  const [note, setNote] = useState("");
  const change = useMutation({
    mutationFn: () => ok(client.PATCH("/api/admin/customers/{workspace_id}/plan", { params: { path: { workspace_id: d.row.id } }, body: { plan, note } })),
    onSuccess: onDone,
  });
  const chosen = plans.data?.plans.find((p) => p.code === plan);
  return (
    <Dialog
      title={`Change plan · ${d.row.name}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={change.isPending} disabled={plan === d.row.plan_code} onClick={() => change.mutate()}>
            Change plan
          </Button>
        </>
      }
    >
      <Field label="Plan">
        <Select value={plan} onChange={(e) => setPlan(e.target.value)}>
          {plans.data?.plans.map((p) => (
            <option key={p.code} value={p.code}>
              {p.name}
            </option>
          ))}
          <option value="unlimited">Unlimited</option>
        </Select>
      </Field>
      {chosen && (
        <p className="text-small text-muted">
          {chosen.name}: {wholeCredits(chosen.monthly_credits)} a month; {chosen.seats ?? "any number of"} people, {chosen.mailboxes ?? "any number of"} mailboxes. Their own overrides and grants stay.
        </p>
      )}
      <Note value={note} onChange={setNote} />
      <Problem error={change.error} />
    </Dialog>
  );
}

function StatusDialog({ d, to, onClose, onDone }: { d: Detail; to: "active" | "paused" | "suspended"; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState("");
  const change = useMutation({
    mutationFn: () => ok(client.PATCH("/api/admin/customers/{workspace_id}/status", { params: { path: { workspace_id: d.row.id } }, body: { status: to, note } })),
    onSuccess: onDone,
  });
  const effect = {
    paused: "Nothing runs for them (no research, no drafts). They can still sign in and read everything.",
    suspended: "Nobody in it can use the workspace, and everyone is signed out now. Nothing is deleted.",
    active: "The engine runs again and people can work normally.",
  }[to];
  return (
    <Dialog
      title={`${to === "active" ? "Make active" : to === "paused" ? "Pause the engine" : "Suspend"} · ${d.row.name}`}
      tone={to === "suspended" ? "danger" : undefined}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={to === "suspended" ? "danger" : "primary"} busy={change.isPending} onClick={() => change.mutate()}>
            Confirm
          </Button>
        </>
      }
    >
      <p className="text-body">{effect}</p>
      <Note value={note} onChange={setNote} />
      <Problem error={change.error} />
    </Dialog>
  );
}

// ------------------------------------------------------------------ tabs

const Meters = ({ d }: { d: Detail }) => (
  <div className="flex items-center justify-between gap-3 text-body">
    <span>AI credits</span>
    <UseBar used={Math.round(d.row.credits.used_milli / 1000)} total={d.row.credits.allowance} />
  </div>
);

function Overview({ d, onChange }: { d: Detail; onChange: () => void }) {
  const resume = useMutation({
    mutationFn: () => ok(client.POST("/api/admin/customers/{workspace_id}/resume", { params: { path: { workspace_id: d.row.id } } })),
    onSuccess: onChange,
  });
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="This period" subtitle={`Renews ${new Date(d.row.period_end).toLocaleDateString()}`}>
        <Meters d={d} />
      </Card>
      <Card title="Waiting work" subtitle="Stopped only because the AI credits ran out. It continues by itself when credits are back.">
        {d.row.waiting === 0 ? (
          <p className="text-body text-muted">Nothing is waiting.</p>
        ) : (
          <div className="flex items-center justify-between gap-3 text-body">
            <span>{d.row.waiting} lead(s) waiting</span>
            <Button size="sm" busy={resume.isPending} onClick={() => resume.mutate()}>
              Resume all now
            </Button>
          </div>
        )}
        <Problem error={resume.error instanceof ApiProblem && resume.error.code === "no_credits" ? new Error(`${resume.error.message}`) : resume.error} className="mt-2" />
      </Card>
      <Card title="Totals">
        <dl className="space-y-1.5 text-body">
          <Line label="Leads" value={d.row.leads} />
          <Line label="AI credits used this month" value={credits(d.row.credits_milli)} />
          <Line label="What it cost the platform" value={usd(d.row.cost_micro_usd)} />
          <Line label="Last active" value={d.row.last_active ? new Date(d.row.last_active).toLocaleString() : "never"} />
          <Line label="On this plan since" value={d.plan_started_at ? new Date(d.plan_started_at).toLocaleDateString() : "—"} />
        </dl>
      </Card>
    </div>
  );
}

const Line = ({ label, value }: { label: string; value: ReactNode }) => (
  <div className="flex justify-between gap-3">
    <dt className="text-muted">{label}</dt>
    <dd className="font-medium">{value}</dd>
  </div>
);

function Limits({ d, onChange }: { d: Detail; onChange: () => void }) {
  const [edit, setEdit] = useState<string | null>(null);
  const revoke = useMutation({
    mutationFn: (v: { kind: "grant" | "override"; id: string }) =>
      v.kind === "grant"
        ? ok(client.DELETE("/api/admin/customers/{workspace_id}/grants/{grant_id}", { params: { path: { workspace_id: d.row.id, grant_id: v.id } } }))
        : ok(client.DELETE("/api/admin/customers/{workspace_id}/overrides/{override_id}", { params: { path: { workspace_id: d.row.id, override_id: v.id } } })),
    onSuccess: onChange,
  });
  const live = d.overrides.filter((o) => !o.revoked_at);
  return (
    <div className="space-y-4">
      <Card tour="admin-limits" title="AI credits" subtitle={`Period ${new Date(d.row.period_start).toLocaleDateString()} to ${new Date(d.row.period_end).toLocaleDateString()}`}>
        <Table>
          <thead>
            <tr>
              <Th>Plan, a month</Th>
              <Th>Override</Th>
              <Th>Grants</Th>
              <Th>Used</Th>
              <Th>Left</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            <tr>
              <Td>{wholeCredits(d.row.credits.plan_monthly)}</Td>
              <Td>{d.row.credits.monthly !== d.row.credits.plan_monthly ? wholeCredits(d.row.credits.monthly) : "—"}</Td>
              <Td>{d.row.credits.granted ? `+${wholeCredits(d.row.credits.granted)}` : "—"}</Td>
              <Td>{credits(d.row.credits.used_milli)}</Td>
              <Td className={d.row.credits.remaining_milli === 0 ? "font-semibold text-error" : ""}>{d.row.credits.remaining_milli == null ? "No limit" : credits(d.row.credits.remaining_milli)}</Td>
              <Td className="text-right">
                <Button size="sm" variant="ghost" onClick={() => setEdit("monthly_credits")}>
                  Change monthly
                </Button>
              </Td>
            </tr>
          </tbody>
        </Table>
      </Card>
      <Card title="History" subtitle="Every override and grant. Withdrawing one keeps its record.">
        <Problem error={revoke.error} className="mb-2" />
        <ul className="divide-y divide-line text-body">
          {[
            ...d.grants.map((g) => ({ at: g.created_at, id: g.id, kind: "grant" as const, dead: g.revoked_at, text: `+${wholeCredits(g.amount)}${g.step ? ` (was ${stepName(g.step).toLowerCase()})` : ""}`, extra: g.expires_at ? `expires ${new Date(g.expires_at).toLocaleDateString()}` : "never expires", note: g.note })),
            ...d.overrides.map((o) => ({ at: o.created_at, id: o.id, kind: "override" as const, dead: o.revoked_at, text: `${o.key.replace("limit.", "old step limit: ").replace("feature.", "feature: ")} → ${o.value === null ? "unlimited" : String(o.value)}`, extra: o.expires_at ? `until ${new Date(o.expires_at).toLocaleDateString()}` : "no end", note: o.note })),
          ]
            .sort((a, b) => b.at.localeCompare(a.at))
            .map((item) => (
              <li key={`${item.kind}-${item.id}`} className={`flex flex-wrap items-center justify-between gap-2 py-2 ${item.dead ? "text-muted line-through" : ""}`}>
                <span>
                  <strong className="font-medium">{item.text}</strong> · <When iso={item.at} /> · {item.extra}
                  {item.note && <> · “{item.note}”</>}
                </span>
                {!item.dead && (
                  <Button size="sm" variant="danger-ghost" busy={revoke.isPending && revoke.variables?.id === item.id} onClick={() => revoke.mutate({ kind: item.kind, id: item.id })}>
                    {item.kind === "grant" ? "Revoke" : "Undo"}
                  </Button>
                )}
              </li>
            ))}
          {d.grants.length + d.overrides.length === 0 && <li className="py-2 text-muted">Nothing yet.</li>}
        </ul>
      </Card>
      {live.length > 0 && <p className="text-small text-muted">{live.length} active override(s) apply on top of the plan.</p>}
      {edit && <OverrideDialog d={d} keyName={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); onChange(); }} />}
    </div>
  );
}

const OVERRIDE_LABELS: Record<string, string> = {
  monthly_credits: "AI credits a month",
  seats: "People (seats)",
  mailboxes: "Mailboxes",
  active_campaigns: "Active campaigns",
  max_leads_per_run: "Leads per run",
  max_prospect_budget: "Most they may set as budget per lead (AI credits)",
};

function OverrideDialog({ d, keyName, onClose, onDone }: { d: Detail; keyName: string; onClose: () => void; onDone: () => void }) {
  const label = OVERRIDE_LABELS[keyName] ?? keyName;
  const current = { monthly_credits: d.row.credits.monthly, seats: d.row.seats, mailboxes: d.row.mailbox_limit, active_campaigns: d.row.active_campaigns, max_leads_per_run: d.row.max_leads_per_run, max_prospect_budget: d.row.max_prospect_budget_credits }[keyName];
  const [unlimited, setUnlimited] = useState(current === null);
  const [value, setValue] = useState(current ?? 0);
  const [until, setUntil] = useState("");
  const [note, setNote] = useState("");
  const save = useMutation({
    mutationFn: () => ok(client.PUT("/api/admin/customers/{workspace_id}/overrides", { params: { path: { workspace_id: d.row.id } }, body: { key: keyName, value: unlimited ? null : value, expires_at: until ? new Date(`${until}T23:59:59`).toISOString() : null, note } })),
    onSuccess: onDone,
  });
  return (
    <Dialog
      title={`${label} · ${d.row.name}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={save.isPending} onClick={() => save.mutate()}>
            Set
          </Button>
        </>
      }
    >
      <p className="text-small text-muted">Now: {current ?? "unlimited"}. This replaces the plan's value for this customer only.</p>
      <Checkbox label="No limit" checked={unlimited} onChange={setUnlimited} />
      {!unlimited && (
        <Field label="New limit">
          <Input type="number" min={0} value={value} onChange={(e) => setValue(Math.max(0, Number(e.target.value)))} className="w-full" />
        </Field>
      )}
      <Field label="Until" hint="Optional. Empty: no end.">
        <Input type="date" value={until} onChange={(e) => setUntil(e.target.value)} className="w-full" />
      </Field>
      <Note value={note} onChange={setNote} />
      <Problem error={save.error} />
    </Dialog>
  );
}

const FEATURES: [string, string, string][] = [
  ["directory_bypass", "Can skip the lead directory", "May search vendors directly instead of the shared verified directory."],
  ["discovery", "Can find companies by search", "Discovery from an ideal-customer description."],
  ["follow_ups", "Follow-ups", "Later follow-up emails (not built yet)."],
  ["auto_send", "Automatic sending", "Later sending without a person pressing Send (not built yet)."],
];

function Access({ d, onChange }: { d: Detail; onChange: () => void }) {
  const [edit, setEdit] = useState<string | null>(null);
  const toggle = useMutation({
    mutationFn: (v: { feature: string; on: boolean }) => ok(client.PUT("/api/admin/customers/{workspace_id}/overrides", { params: { path: { workspace_id: d.row.id } }, body: { key: `feature.${v.feature}`, value: v.on, note: "set in the console" } })),
    onSuccess: onChange,
  });
  const numbers: [string, number | null][] = [
    ["seats", d.row.seats],
    ["mailboxes", d.row.mailbox_limit],
    ["active_campaigns", d.row.active_campaigns],
    ["max_leads_per_run", d.row.max_leads_per_run],
    ["max_prospect_budget", d.row.max_prospect_budget_credits],
  ];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Status">
        <div className="space-y-2 text-body">
          <div>
            <AccessPill row={d.row} /> <span className="ml-2 text-muted">{d.row.status}</span>
          </div>
          <p className="text-small text-muted">Pause, suspend or reopen from the More menu above.</p>
        </div>
      </Card>
      <Card title="Features" subtitle="Switch a capability on or off for this customer.">
        <ul className="space-y-3">
          {FEATURES.map(([key, label, why]) => (
            <li key={key}>
              <Checkbox label={label} hint={why} checked={d.row.features.includes(key)} disabled={toggle.isPending} onChange={(on) => toggle.mutate({ feature: key, on })} />
            </li>
          ))}
        </ul>
        <Problem error={toggle.error} className="mt-2" />
      </Card>
      <Card title="Allowances" subtitle="From the plan, unless changed for this customer." className="lg:col-span-2">
        <Table>
          <tbody>
            {numbers.map(([key, value]) => (
              <tr key={key}>
                <Td className="font-medium">{OVERRIDE_LABELS[key]}</Td>
                <Td>{value ?? "No limit"}</Td>
                <Td className="text-right">
                  <Button size="sm" variant="ghost" onClick={() => setEdit(key)}>
                    Edit
                  </Button>
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      {edit && <OverrideDialog d={d} keyName={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); onChange(); }} />}
    </div>
  );
}

function Members({ d, onChange }: { d: Detail; onChange: () => void }) {
  const base = { workspace_id: d.row.id };
  const [removing, setRemoving] = useState<{ id: string; label: string } | null>(null);
  const role = useMutation({
    mutationFn: async (v: { id: string; role: "admin" | "member" }) => {
      const r = await client.PATCH("/api/admin/customers/{workspace_id}/members/{user_id}", { params: { path: { ...base, user_id: v.id } }, body: { role: v.role } });
      if (!r.response.ok) throw new Error("That change was refused: a workspace keeps at least one admin.");
    },
    onSuccess: onChange,
  });
  const remove = useMutation({
    mutationFn: async (id: string) => {
      const r = await client.DELETE("/api/admin/customers/{workspace_id}/members/{user_id}", { params: { path: { ...base, user_id: id } } });
      if (!r.response.ok) throw new Error("That change was refused: a workspace keeps at least one admin.");
    },
    onSuccess: () => {
      setRemoving(null);
      onChange();
    },
  });
  return (
    <Card title="Members" subtitle="Who can sign in to this workspace. Changes here are recorded in the audit log.">
      <Problem error={role.error} className="mb-2" />
      <Table>
        <thead>
          <tr>
            <Th>Person</Th>
            <Th>Role</Th>
            <Th>Last signed in</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {d.members.map((m) => (
            <tr key={m.user_id}>
              <Td>
                <span className="font-medium">{m.name || m.email}</span>
                {m.name && <span className="block text-label text-muted">{m.email}</span>}
              </Td>
              <Td>
                <Select aria-label={`Role of ${m.email}`} value={m.role} onChange={(e) => role.mutate({ id: m.user_id, role: e.target.value as "admin" | "member" })}>
                  <option value="admin">Admin</option>
                  <option value="member">Member</option>
                </Select>
              </Td>
              <Td className="text-muted">{m.last_login_at ? new Date(m.last_login_at).toLocaleString() : "Never"}</Td>
              <Td className="text-right">
                <Button size="sm" variant="danger-ghost" onClick={() => setRemoving({ id: m.user_id, label: m.email })}>
                  Remove
                </Button>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      {removing && (
        <Confirm title={`Remove ${removing.label}?`} confirmLabel="Remove" busy={remove.isPending} error={remove.error} onClose={() => setRemoving(null)} onConfirm={() => remove.mutate(removing.id)}>
          They lose access to this workspace at once. Their leads and work stay.
        </Confirm>
      )}
    </Card>
  );
}

function Mailboxes({ d, onChange }: { d: Detail; onChange: () => void }) {
  const [asking, setAsking] = useState<{ id: string; address: string } | null>(null);
  const reconnect = useMutation({
    mutationFn: async (id: string) => {
      const r = await client.POST("/api/admin/customers/{workspace_id}/mailboxes/{mailbox_id}/reconnect", { params: { path: { workspace_id: d.row.id, mailbox_id: id } } });
      if (!r.response.ok) throw new Error("That did not work.");
    },
    onSuccess: () => {
      setAsking(null);
      onChange();
    },
  });
  return (
    <Card title="Mailboxes" subtitle="Addresses and health only; the customer connects and manages them.">
      {d.mailboxes.length === 0 ? (
        <p className="text-body text-muted">None connected.</p>
      ) : (
        <Table>
          <thead>
            <tr>
              <Th>Address</Th>
              <Th>Type</Th>
              <Th>Status</Th>
              <Th>DNS</Th>
              <Th>Last checked</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {d.mailboxes.map((m) => (
              <tr key={m.id}>
                <Td className="font-mono text-small">{m.address}</Td>
                <Td>{m.gateway}</Td>
                <Td>{m.status === "active" ? <Pill tone="good">working</Pill> : <Pill tone="error">{m.status.replace("_", " ")}</Pill>}</Td>
                <Td>{m.dns_ok === null ? "not checked" : m.dns_ok ? "ok" : "problems"}</Td>
                <Td className="text-muted">{m.last_checked_at ? new Date(m.last_checked_at).toLocaleString() : "—"}</Td>
                <Td className="text-right">
                  {m.status !== "needs_reconnect" && (
                    <Button size="sm" variant="ghost" onClick={() => setAsking({ id: m.id, address: m.address })}>
                      Force reconnect
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      {asking && (
        <Confirm title={`Make ${asking.address} reconnect?`} confirmLabel="Force reconnect" busy={reconnect.isPending} error={reconnect.error} onClose={() => setAsking(null)} onConfirm={() => reconnect.mutate(asking.id)}>
          Nothing is saved through this mailbox until the customer signs in to it again. Use it when a token may have leaked.
        </Confirm>
      )}
    </Card>
  );
}

function Activity({ d }: { d: Detail }) {
  return (
    <Card title="Activity" subtitle="Admin actions on this customer and its key events.">
      {d.activity.length === 0 ? (
        <p className="text-body text-muted">Nothing yet.</p>
      ) : (
        <ul className="divide-y divide-line text-body">
          {d.activity.map((a) => (
            <li key={a.id} className="flex flex-wrap items-baseline gap-x-2 py-1.5">
              <When iso={a.at} time />
              <strong className="font-medium">{a.action.replaceAll("_", " ")}</strong>
              {a.actor && <span className="text-muted">by {a.actor}</span>}
              {a.note && <span className="text-muted">· “{a.note}”</span>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
