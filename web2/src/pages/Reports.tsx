import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Card, Label, PageHeader, Problem, Segmented, Skeleton, Stat, Table, Td, Th } from "../components/ui";
import { percent, usd } from "../lib/format";
import { callOutcome, describe, describeHold } from "../lib/status";
import { BudgetMeter, ProviderBars } from "./Dashboard";

export function ReportsPage() {
  const [days, setDays] = useState(30);
  const cost = useQuery({ queryKey: ["cost", days], queryFn: () => ok(client.GET("/api/reports/cost", { params: { query: { days } } })) });
  const quality = useQuery({ queryKey: ["quality"], queryFn: () => ok(client.GET("/api/reports/quality")) });
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const ceiling = settings.data?.budget_per_prospect_micro_usd as number | null | undefined;
  const c = cost.data;
  const q = quality.data;
  const outcomes = c?.outcomes ?? {};
  const calls = Object.values(outcomes).reduce((sum, n) => sum + n, 0);
  const holds = Object.entries(q?.holds ?? {}).sort((a, b) => b[1] - a[1]);
  const widestHold = Math.max(1, ...holds.map(([, n]) => n));

  return (
    <>
      <PageHeader
        title="Reports"
        subtitle="Are the emails good enough to send unedited, and does each prospect stay under budget?"
        actions={
          <Segmented
            label="Period for spend"
            value={days}
            onChange={setDays}
            options={[
              [7, "7 days"],
              [30, "30 days"],
              [90, "90 days"],
              [365, "1 year"],
            ]}
          />
        }
      />
      <Problem error={cost.error ?? quality.error} className="mb-4" />

      <Label className="mb-2">Quality, since the start</Label>
      <div data-tour="reports-quality" className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Sent without an edit" value={percent(q?.unedited_share)} hint={q ? `${q.unedited} of ${q.sent} sent · target 80%` : undefined} tone={q?.unedited_share != null ? (q.unedited_share >= 0.8 ? "good" : "attention") : undefined} />
        <Stat label="Flagged by the checks" value={percent(q?.flag_rate)} hint={q ? `${q.flagged} of ${q.written} written` : undefined} />
        <Stat label="Catch-all addresses" value={percent(q?.catch_all_share)} hint="Servers that accept any address" />
        <Stat label="Companies" value={q?.companies ?? "–"} hint={q ? `${q.written} emails written` : undefined} />
      </div>

      <div className="mb-6 flex items-center justify-between">
        <Label>Spend, last {days === 365 ? "year" : `${days} days`}</Label>
      </div>
      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Total" value={usd(c?.total, 2)} hint={c ? `${c.paid_calls} paid calls` : undefined} />
        <Stat label="Per prospect" value={c?.per_prospect != null ? usd(c.per_prospect) : "–"} hint={ceiling == null ? "No ceiling set" : `Ceiling ${usd(ceiling, 2)}`} tone="primary" />
        <Stat label="Prospects" value={c?.prospects ?? "–"} hint="Companies with any spend" />
        <Stat label="Answered from cache" value={calls ? percent((outcomes.cache_hit ?? 0) / calls) : "–"} hint={`${outcomes.cache_hit ?? 0} calls reused at no cost`} tone={outcomes.cache_hit ? "good" : undefined} />
      </div>

      <div className="grid grid-cols-1 items-start gap-5 lg:grid-cols-2">
        <Card title="Spend by vendor">
          {cost.isPending ? (
            <Skeleton />
          ) : (
            <>
              {ceiling != null && ceiling > 0 && c?.per_prospect != null && (
                <div className="mb-4 grid grid-cols-2">
                  <BudgetMeter spent={c.per_prospect} ceiling={ceiling} />
                </div>
              )}
              <ProviderBars byProvider={c?.by_provider ?? {}} calls={c?.calls_by_provider ?? {}} total={c?.total ?? 0} />
            </>
          )}
        </Card>

        <Card title="Where leads are held" subtitle="Many catch-all holds mean slow or costly addresses; many company-type holds mean a Companies House key would help.">
          {quality.isPending ? (
            <Skeleton />
          ) : holds.length === 0 ? (
            <p className="text-xs text-muted">No lead is held.</p>
          ) : (
            <ul className="space-y-2">
              {holds.map(([reason, n]) => (
                <li key={reason}>
                  <div className="flex justify-between text-xs">
                    <span>{describeHold(reason).label}</span>
                    <span className="font-mono font-semibold">{n}</span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-container">
                    <div className="h-full bg-attention" style={{ width: `${(n / widestHold) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card title="Cost per vendor" subtitle="The number the vendor bake-off decides on: what each vendor costs per call, and the outcome of every call." className="lg:col-span-2 p-0">
          {cost.isPending ? (
            <div className="p-4">
              <Skeleton />
            </div>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Vendor</Th>
                  <Th className="text-right">Calls</Th>
                  <Th className="text-right">Spend</Th>
                  <Th className="text-right">Average per call</Th>
                  <Th className="text-right">Share of spend</Th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(c?.calls_by_provider ?? {})
                  .sort((a, b) => (c?.by_provider?.[b[0]] ?? 0) - (c?.by_provider?.[a[0]] ?? 0))
                  .map(([vendor, n]) => {
                    const spent = c?.by_provider?.[vendor] ?? 0;
                    return (
                      <tr key={vendor}>
                        <Td className="font-medium">{vendor}</Td>
                        <Td className="text-right font-mono text-xs">{n}</Td>
                        <Td className="text-right font-mono text-xs">{usd(spent)}</Td>
                        <Td className="text-right font-mono text-xs">{n ? usd(spent / n) : "–"}</Td>
                        <Td className="text-right font-mono text-xs">{c?.total ? percent(spent / c.total) : "–"}</Td>
                      </tr>
                    );
                  })}
              </tbody>
            </Table>
          )}
          {calls > 0 && (
            <div className="flex flex-wrap gap-3 border-t border-line p-3">
              {Object.entries(outcomes).map(([outcome, n]) => (
                <span key={outcome} className="inline-flex items-center gap-1.5">
                  <StatusBadge status={describe(callOutcome, outcome)} />
                  <span className="font-mono text-xs">{n}</span>
                </span>
              ))}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
