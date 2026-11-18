import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { wholeCredits } from "../lib/format";
import { Button, Callout, Card, Checkbox, Dialog, Field, Input, PageHeader, Problem, QueryState, Table, Td } from "../ui/compat";
import { Pill } from "./bits";

type Plan = Schemas["PlanDefinition"];
type Catalog = Schemas["PlansOut"];
const FEATURES = ["discovery", "directory_bypass", "follow_ups", "auto_send"] as const;

export function PlansPage() {
  const queryClient = useQueryClient();
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: () => ok(client.GET("/api/admin/plans")) });
  const [editing, setEditing] = useState<Plan | "new" | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["admin"] });
  const makeDefault = useMutation({
    mutationFn: (v: { plan: string; version: number }) => ok(client.PUT("/api/admin/plans/default", { body: v })),
    onSuccess: refresh,
  });
  const canEdit = plans.data?.can_edit ?? false;
  return (
    <>
      <PageHeader
        title="Plans"
        subtitle="The catalog, in AI credits. A change applies to every customer on the plan at once."
        actions={canEdit && <Button onClick={() => setEditing("new")}>New plan</Button>}
      />
      <Problem error={makeDefault.error} className="mb-3" />
      <QueryState query={plans} rows={4} shape="table">
        {(catalog) => (
          <div className="space-y-4">
            {!catalog.can_edit && <Callout tone="info">Only a superadmin can change plans and the value of an AI credit. You can give a customer extra AI credits on their page.</Callout>}
            <CreditValue catalog={catalog} onDone={refresh} />
            <div className="grid gap-4 lg:grid-cols-3">
              {catalog.plans.map((plan) => (
                <Card
                  key={plan.code}
                  title={
                    <span className="flex items-center gap-2">
                      {plan.name}
                      {plan.code === catalog.default_plan && <Pill tone="good">default for new customers</Pill>}
                    </span>
                  }
                  subtitle={`${plan.customers} customer${plan.customers === 1 ? "" : "s"} · ${plan.access_days ? `${plan.access_days} days of access` : "no end date"}`}
                  actions={
                    catalog.can_edit && (
                      <>
                        {plan.code !== catalog.default_plan && (
                          <Button size="sm" variant="secondary" busy={makeDefault.isPending} onClick={() => makeDefault.mutate({ plan: plan.code, version: catalog.version })}>
                            Make default
                          </Button>
                        )}
                        <Button size="sm" onClick={() => setEditing(plan)}>
                          Edit
                        </Button>
                      </>
                    )
                  }
                >
                  <p className="tnum text-title font-semibold">
                    {wholeCredits(plan.monthly_credits)}
                    {plan.monthly_credits != null && <span className="text-small font-normal text-muted"> a month</span>}
                  </p>
                  <Table>
                    <tbody>
                      <tr>
                        <Td>Budget per lead, at most</Td>
                        <Td className="tnum text-right">{wholeCredits(plan.max_prospect_budget_credits)}</Td>
                      </tr>
                      <tr>
                        <Td>People · mailboxes · campaigns</Td>
                        <Td className="tnum text-right">
                          {plan.seats ?? "∞"} · {plan.mailboxes ?? "∞"} · {plan.active_campaigns ?? "∞"}
                        </Td>
                      </tr>
                      <tr>
                        <Td>Features</Td>
                        <Td className="text-right text-small">{plan.features.map((f) => f.replaceAll("_", " ")).join(", ") || "none"}</Td>
                      </tr>
                    </tbody>
                  </Table>
                </Card>
              ))}
            </div>
          </div>
        )}
      </QueryState>
      {editing && plans.data && (
        <EditPlan
          plan={editing === "new" ? null : editing}
          version={plans.data.version}
          customers={editing === "new" ? 0 : editing.customers}
          onClose={() => setEditing(null)}
          onDone={() => {
            setEditing(null);
            refresh();
          }}
        />
      )}
    </>
  );
}

/** What one AI credit stands for: the only place the console shows dollars, for superadmins. */
function CreditValue({ catalog, onDone }: { catalog: Catalog; onDone: () => void }) {
  const [cents, setCents] = useState(String(catalog.credit_value_micro_usd / 10_000));
  const save = useMutation({
    mutationFn: () => ok(client.PUT("/api/admin/plans/credit-value", { body: { credit_value_micro_usd: Math.max(1, Math.round(Number(cents) * 10_000)), version: catalog.version } })),
    onSuccess: onDone,
  });
  return (
    <Card title="What an AI credit stands for" subtitle="Each vendor call is converted into AI credits at this rate when it is made; calls made before a change keep their credits. Model calls use the charges set on the Vendors page instead.">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="One AI credit equals this much vendor cost, in US cents">
          <Input type="number" min={0.0001} step="0.1" value={cents} disabled={!catalog.can_edit} onChange={(e) => setCents(e.target.value)} className="w-32" />
        </Field>
        {catalog.can_edit && (
          <Button variant="secondary" busy={save.isPending} disabled={!(Number(cents) > 0)} onClick={() => save.mutate()}>
            Save rate
          </Button>
        )}
      </div>
      <Problem error={save.error} className="mt-3" />
    </Card>
  );
}

const num = (text: string): number | null => (text.trim() === "" ? null : Math.max(0, Math.round(Number(text))));
const text = (n: number | null | undefined, fallback = "") => (n == null ? fallback : String(n));

function EditPlan({ plan, version, customers, onClose, onDone }: { plan: Plan | null; version: number; customers: number; onClose: () => void; onDone: () => void }) {
  const [code, setCode] = useState(plan?.code ?? "");
  const [name, setName] = useState(plan?.name ?? "");
  const [monthly, setMonthly] = useState(text(plan ? plan.monthly_credits : 100));
  const [budget, setBudget] = useState(text(plan ? plan.max_prospect_budget_credits : 50));
  const [seats, setSeats] = useState(text(plan?.seats));
  const [mailboxes, setMailboxes] = useState(text(plan?.mailboxes));
  const [campaigns, setCampaigns] = useState(text(plan?.active_campaigns));
  const [days, setDays] = useState(text(plan?.access_days));
  const [features, setFeatures] = useState<string[]>(plan?.features ?? ["discovery"]);
  const save = useMutation({
    mutationFn: () =>
      ok(
        client.PUT("/api/admin/plans/{code}", {
          params: { path: { code: code.trim() } },
          body: {
            name: name.trim(),
            monthly_credits: num(monthly),
            seats: num(seats),
            mailboxes: num(mailboxes),
            active_campaigns: num(campaigns),
            max_prospect_budget_credits: num(budget),
            max_leads_per_run: plan?.max_leads_per_run ?? null,
            features,
            access_days: num(days),
            version,
          },
        }),
      ),
    onSuccess: onDone,
  });
  return (
    <Dialog
      title={plan ? `Edit ${plan.name}` : "New plan"}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={save.isPending} disabled={!code.trim() || !name.trim()} onClick={() => save.mutate()}>
            {plan && customers ? `Save · applies to ${customers} customer${customers === 1 ? "" : "s"}` : "Save"}
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="Code" hint={plan ? "Fixed." : "Letters, digits, - and _"}>
          <Input value={code} disabled={Boolean(plan)} onChange={(e) => setCode(e.target.value)} className="w-full" />
        </Field>
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} className="w-full" />
        </Field>
      </div>
      <p className="text-small text-muted">Leave a number empty for no limit.</p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="AI credits a month" hint="Every vendor and model call uses them.">
          <Input type="number" min={0} step="100" value={monthly} onChange={(e) => setMonthly(e.target.value)} placeholder="No limit" className="w-full" />
        </Field>
        <Field label="Budget per lead, at most" hint="The most a customer may set, in AI credits.">
          <Input type="number" min={0} value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="No limit" className="w-full" />
        </Field>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <Field label="People">
          <Input type="number" min={0} value={seats} onChange={(e) => setSeats(e.target.value)} placeholder="No limit" className="w-full" />
        </Field>
        <Field label="Mailboxes">
          <Input type="number" min={0} value={mailboxes} onChange={(e) => setMailboxes(e.target.value)} placeholder="No limit" className="w-full" />
        </Field>
        <Field label="Campaigns">
          <Input type="number" min={0} value={campaigns} onChange={(e) => setCampaigns(e.target.value)} placeholder="No limit" className="w-full" />
        </Field>
      </div>
      <Field label="Days of access for a new customer" hint="Empty: no end date.">
        <Input type="number" min={1} value={days} onChange={(e) => setDays(e.target.value)} className="w-40" />
      </Field>
      <fieldset className="space-y-1">
        <legend className="mb-1 text-small font-medium">Features</legend>
        {FEATURES.map((f) => (
          <Checkbox key={f} label={f.replaceAll("_", " ")} checked={features.includes(f)} onChange={(on) => setFeatures(on ? [...features, f] : features.filter((x) => x !== f))} />
        ))}
      </fieldset>
      <Problem error={save.error} />
    </Dialog>
  );
}
