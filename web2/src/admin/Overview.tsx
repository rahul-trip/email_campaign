import { useQuery } from "@tanstack/react-query";
import { CheckCircle2 } from "lucide-react";
import { client, ok } from "../api/client";
import { Card, Empty, PageHeader, QueryState, Stat } from "../components/ui";
import { usd } from "../lib/format";
import { A } from "./nav";
import { When } from "./bits";

const KIND = { credit_request: "Asked for more credits", access_ending: "Access ending", mailbox: "Mailbox needs attention" } as const;
const FIX = { credit_request: "Grant", access_ending: "Extend", mailbox: "Open" } as const;

export function OverviewPage() {
  const overview = useQuery({ queryKey: ["admin", "overview"], queryFn: () => ok(client.GET("/api/admin/overview")), refetchInterval: 30_000 });
  return (
    <>
      <PageHeader title="Overview" subtitle="What needs a decision today. Counts and sums only: you never see a customer's leads here." />
      <QueryState query={overview} rows={6}>
        {(o) => {
          const providers = Object.entries(o.spend_by_provider).sort((a, b) => b[1] - a[1]);
          const top = Math.max(1, ...providers.map(([, v]) => v));
          return (
            <div className="space-y-5">
              <div data-tour="admin-figures" className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
                <Stat label="Active customers" value={o.customers} hint={o.expiring ? `${o.expiring} end within 7 days` : undefined} tone={o.expiring ? "attention" : undefined} />
                <Stat label="Leads added" value={o.leads_added} hint="this month" />
                <Stat label="Drafts made" value={o.drafts_made} hint="this month" />
                <Stat label="Vendor spend" value={usd(o.spend_micro_usd)} hint="this month, all customers" />
                <Stat label="Waiting for credits" value={o.waiting} hint={o.waiting_customers ? `${o.waiting_customers} customer${o.waiting_customers === 1 ? "" : "s"}` : undefined} tone={o.waiting ? "attention" : undefined} />
              </div>
              <div className="grid gap-5 lg:grid-cols-2">
                <Card tour="admin-attention" title="Needs attention">
                  {o.attention.length === 0 ? (
                    <Empty icon={<CheckCircle2 className="size-7 text-good" />} title="Nothing needs you">
                      Credit requests, access that is about to end and mailbox problems show here.
                    </Empty>
                  ) : (
                    <ul className="divide-y divide-line">
                      {o.attention.map((a, i) => (
                        <li key={i} className="flex items-center justify-between gap-3 py-2.5 text-[13px]">
                          <span>
                            <strong>{a.workspace_name}</strong>
                            <span className="block text-xs text-muted">
                              {KIND[a.kind]}: {a.detail}
                            </span>
                          </span>
                          <A to="/customers/$id" params={{ id: a.workspace_id }} className="shrink-0 rounded-lg border border-outline px-2.5 py-1 text-xs font-semibold hover:bg-surface-low">
                            {FIX[a.kind]}
                          </A>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
                <Card title="Spend by vendor" subtitle="This month, all customers.">
                  {providers.length === 0 ? (
                    <p className="text-[13px] text-muted">No vendor calls yet this month.</p>
                  ) : (
                    <ul className="space-y-2 text-[13px]">
                      {providers.map(([name, micro]) => (
                        <li key={name}>
                          <div className="flex justify-between">
                            <span>{name}</span>
                            <span className="font-mono">{usd(micro)}</span>
                          </div>
                          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-container">
                            <div className="h-full rounded-full bg-primary-container" style={{ width: `${(micro / top) * 100}%` }} />
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>
              <Card title="Recent admin activity" actions={<A to="/audit" className="text-xs font-semibold text-primary hover:underline">Audit log</A>}>
                {o.activity.length === 0 ? (
                  <p className="text-[13px] text-muted">Nothing yet.</p>
                ) : (
                  <ul className="divide-y divide-line text-[13px]">
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

