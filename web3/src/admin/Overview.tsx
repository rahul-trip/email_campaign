import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Card, Empty, Field, Input, PageHeader, Problem, QueryState, Stat } from "../ui/compat";
import { credits, usd } from "../lib/format";
import { A } from "./nav";
import { When } from "./bits";

const KIND = { credit_request: "Asked for more credits", access_ending: "Access ending", mailbox: "Mailbox needs attention", deletion_due: "Waiting to be deleted", workspace_request: "New workspace" } as const;
const FIX = { credit_request: "Grant", access_ending: "Extend", mailbox: "Open", deletion_due: "Open", workspace_request: "Open" } as const;

export function OverviewPage() {
  const overview = useQuery({ queryKey: ["admin", "overview"], queryFn: () => ok(client.GET("/api/admin/overview")), refetchInterval: 30_000 });
  return (
    <>
      <PageHeader title="Overview" subtitle="What needs a decision today. Counts and sums only: you never see a customer's leads here." />
      <QueryState query={overview} rows={6}>
        {(o) => {
          const providers = Object.entries(o.credits_by_provider).sort((a, b) => b[1] - a[1]);
          const top = Math.max(1, ...providers.map(([, v]) => v));
          const attention = o.attention.filter((a) => a.kind !== "workspace_request"); // those have their own card
          return (
            <div className="space-y-5">
              <div data-tour="admin-figures" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                <Stat label="Active customers" value={o.customers} hint={o.expiring ? `${o.expiring} end within 7 days` : undefined} tone={o.expiring ? "attention" : undefined} />
                <Stat label="Leads added" value={o.leads_added} hint="this month" />
                <Stat label="Drafts made" value={o.drafts_made} hint="this month" />
                <Stat label="AI credits used" value={credits(o.credits_milli)} hint="this month, all customers" />
                <Stat label="Platform cost" value={usd(o.cost_micro_usd)} hint="what vendors and the model billed, this month" />
                <Stat label="Waiting for credits" value={o.waiting} hint={o.waiting_customers ? `${o.waiting_customers} customer${o.waiting_customers === 1 ? "" : "s"}` : undefined} tone={o.waiting ? "attention" : undefined} />
              </div>
              <WorkspaceRequests />
              <div className="grid gap-5 lg:grid-cols-2">
                <Card tour="admin-attention" title="Needs attention">
                  {attention.length === 0 ? (
                    <Empty icon={<CheckCircle2 className="size-7 text-good" />} title="Nothing needs you">
                      Credit requests, access that is about to end and mailbox problems show here.
                    </Empty>
                  ) : (
                    <ul className="divide-y divide-line">
                      {attention.map((a, i) => (
                        <li key={i} className="flex items-center justify-between gap-3 py-2.5 text-body">
                          <span>
                            <strong>{a.workspace_name}</strong>
                            <span className="block text-small text-muted">
                              {KIND[a.kind]}: {a.detail}
                            </span>
                          </span>
                          <A to="/customers/$id" params={{ id: a.workspace_id }} className="shrink-0 rounded-lg border border-line-strong px-2.5 py-1 text-small font-semibold hover:bg-surface-2">
                            {FIX[a.kind]}
                          </A>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
                <Card title="AI credits by vendor" subtitle="This month, all customers, with what each vendor billed the platform.">
                  {providers.length === 0 ? (
                    <p className="text-body text-muted">No vendor calls yet this month.</p>
                  ) : (
                    <ul className="space-y-2 text-body">
                      {providers.map(([name, micro]) => (
                        <li key={name}>
                          <div className="flex justify-between">
                            <span>{name}</span>
                            <span className="font-mono">
                              {credits(micro)} · {usd(o.cost_by_provider[name])}
                            </span>
                          </div>
                          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-3">
                            <div className="h-full rounded-full bg-primary" style={{ width: `${(micro / top) * 100}%` }} />
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
              <Card title="Recent admin activity" actions={<A to="/audit" className="text-small font-semibold text-primary hover:underline">Audit log</A>}>
                {o.activity.length === 0 ? (
                  <p className="text-body text-muted">Nothing yet.</p>
                ) : (
                  <ul className="divide-y divide-line text-body">
                    {o.activity.map((a) => (
                      <li key={a.id} className="flex flex-wrap items-baseline gap-x-2 py-1.5">
                        <When iso={a.at} time />
                        <span className="font-medium">{a.action.replaceAll("_", " ")}</span>
                        {a.workspace && <span className="text-muted">· {a.workspace}</span>}
                        {a.note && <span className="text-muted">· “{a.note}”</span>}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          );
        }}
      </QueryState>
    </>
  );
}


/** People whose workspace was deleted and who asked for a new one. Shown only when there are some. */
function WorkspaceRequests() {
  const requests = useQuery({ queryKey: ["admin", "workspace-requests"], queryFn: () => ok(client.GET("/api/admin/workspace-requests")), refetchInterval: 30_000 });
  if (!requests.data?.length) return null;
  return (
    <Card title="Asked for a new workspace" subtitle="Their workspace was deleted. Approving makes a new, empty workspace with them as its admin.">
      <ul className="divide-y divide-line">
        {requests.data.map((r) => (
          <RequestRow key={r.user_id} r={r} />
        ))}
      </ul>
    </Card>
  );
}

function RequestRow({ r }: { r: Schemas["WorkspaceRequestOut"] }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(r.name);
  const done = () => void queryClient.invalidateQueries({ queryKey: ["admin"] });
  const path = { params: { path: { user_id: r.user_id } } };
  const approve = useMutation({
    mutationFn: () => ok(client.POST("/api/admin/workspace-requests/{user_id}/approve", { ...path, body: { name: name.trim(), website: r.website } })),
    onSuccess: done,
  });
  const dismiss = useMutation({ mutationFn: () => ok(client.POST("/api/admin/workspace-requests/{user_id}/dismiss", path)), onSuccess: done });
  return (
    <li className="space-y-2 py-3 text-body">
      <div>
        <strong>{r.email}</strong> <When iso={r.created_at} />
        {r.note && <span className="block text-small text-muted">“{r.note}”</span>}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Workspace name">
          <Input value={name} onChange={(e) => setName(e.target.value)} className="h-8 w-64" />
        </Field>
        <Button size="sm" busy={approve.isPending} disabled={!name.trim()} onClick={() => approve.mutate()}>
          Make the workspace
        </Button>
        <Button size="sm" variant="secondary" busy={dismiss.isPending} onClick={() => dismiss.mutate()}>
          Dismiss
        </Button>
      </div>
      <Problem error={approve.error ?? dismiss.error} />
    </li>
  );
}
