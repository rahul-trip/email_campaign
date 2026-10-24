import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Card, Checkbox, Dialog, Field, Input, PageHeader, Problem, QueryState, Table, Td } from "../components/ui";
import { Pill, stepName } from "./bits";

type Plan = Schemas["PlanDefinition"];
const STEPS = ["discovery", "manual", "research", "email", "copy", "deliver", "rewrite"] as const;
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
  return (
    <>
      <PageHeader title="Plans" subtitle="The catalog. A change applies to every customer on the plan at once." actions={<Button onClick={() => setEditing("new")}>New plan</Button>} />
      <Problem error={makeDefault.error} className="mb-3" />
      <QueryState query={plans} rows={4}>
        {(catalog) => (
          <div className="grid gap-4 lg:grid-cols-2">
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
                }
              >
                <Table>
                  <tbody>
                    {STEPS.map((s) => (
                      <tr key={s}>
                        <Td>{stepName(s)}</Td>
                        <Td className="text-right font-mono">{plan.limits[s] ?? "∞"} / month</Td>
                      </tr>
                    ))}
                    <tr>
                      <Td>People · mailboxes · campaigns</Td>
                      <Td className="text-right font-mono">
                        {plan.seats ?? "∞"} · {plan.mailboxes ?? "∞"} · {plan.active_campaigns ?? "∞"}
                      </Td>
                    </tr>
                    <tr>
                      <Td>Features</Td>
                      <Td className="text-right text-xs">{plan.features.join(", ") || "none"}</Td>
                    </tr>
                  </tbody>
                </Table>
              </Card>
            ))}
          </div>
        )}
      </QueryState>
      {editing && plans.data && <EditPlan plan={editing === "new" ? null : editing} version={plans.data.version} customers={editing === "new" ? 0 : editing.customers} onClose={() => setEditing(null)} onDone={() => { setEditing(null); refresh(); }} />}
    </>
  );
}

const num = (text: string): number | null => (text.trim() === "" ? null : Math.max(0, Number(text)));

function EditPlan({ plan, version, customers, onClose, onDone }: { plan: Plan | null; version: number; customers: number; onClose: () => void; onDone: () => void }) {
  const [code, setCode] = useState(plan?.code ?? "");
  const [name, setName] = useState(plan?.name ?? "");
  const [limits, setLimits] = useState<Record<string, string>>(Object.fromEntries(STEPS.map((s) => [s, plan?.limits[s] == null ? "" : String(plan.limits[s])])));
  const [seats, setSeats] = useState(plan?.seats == null ? "" : String(plan.seats ?? ""));
  const [mailboxes, setMailboxes] = useState(plan?.mailboxes == null ? "" : String(plan.mailboxes));
  const [campaigns, setCampaigns] = useState(plan?.active_campaigns == null ? "" : String(plan.active_campaigns));
  const [days, setDays] = useState(plan?.access_days == null ? "" : String(plan.access_days));
  const [features, setFeatures] = useState<string[]>(plan?.features ?? ["discovery"]);
  const save = useMutation({
    mutationFn: () =>
      ok(
        client.PUT("/api/admin/plans/{code}", {
          params: { path: { code: code.trim() } },
          body: {
            name: name.trim(),
            limits: Object.fromEntries(STEPS.filter((s) => limits[s] !== "").map((s) => [s, num(limits[s]!)])) as never,
            seats: num(seats),
            mailboxes: num(mailboxes),
            active_campaigns: num(campaigns),
            max_prospect_budget_micro_usd: plan?.max_prospect_budget_micro_usd ?? 500_000,
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
      <p className="text-xs text-muted">Leave a number empty for no limit. Limits are per month.</p>
      <div className="grid grid-cols-2 gap-3">
        {STEPS.map((s) => (
          <Field key={s} label={stepName(s)}>
            <Input type="number" min={0} value={limits[s]} onChange={(e) => setLimits({ ...limits, [s]: e.target.value })} placeholder="No limit" className="w-full" />
          </Field>
        ))}
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
        <legend className="mb-1 text-xs font-medium">Features</legend>
        {FEATURES.map((f) => (
          <Checkbox key={f} label={f.replaceAll("_", " ")} checked={features.includes(f)} onChange={(on) => setFeatures(on ? [...features, f] : features.filter((x) => x !== f))} />
        ))}
      </fieldset>
      <Problem error={save.error} />
    </Dialog>
  );
}
