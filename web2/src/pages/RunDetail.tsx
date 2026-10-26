import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { client, ok, type Schemas } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Callout, Card, Empty, PageHeader, Problem, QueryState, Skeleton, Stat, Table, Td, Th, buttonClass } from "../components/ui";
import { cx } from "../lib/cx";
import { ago, duration, usd, when, words } from "../lib/format";
import { OUTCOME_LABEL, STAGES, STAGE_LABEL, countsOf, discoveryLine, totalsOf } from "../lib/runs";
import { describe, leadStatus, runStatus } from "../lib/status";

type Lead = Schemas["RunLeadOut"];

const OUTCOME: Record<string, { label: string; tone: string }> = {
  moved: { label: "Moved on", tone: "bg-good-container text-on-good-container" },
  held: { label: "Held", tone: "bg-attention-container text-on-attention-container" },
  failed: { label: "Failed", tone: "bg-error-container text-on-error-container" },
  deferred: { label: "Will retry", tone: "bg-surface-container text-muted" },
};
const ORDER = ["failed", "held", "deferred", "moved"];

/** One run: what it was asked to do, and every lead it moved, held, failed or put off. */
export function RunDetailPage() {
  const { runId } = useParams({ from: "/runs/$runId" });
  const path = { params: { path: { run_id: runId } } };
  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => ok(client.GET("/api/runs/{run_id}", path)),
    refetchInterval: (query) => (["queued", "running"].includes(query.state.data?.status ?? "") ? 3000 : false),
  });
  const live = ["queued", "running"].includes(run.data?.status ?? "");
  const leads = useQuery({
    queryKey: ["run-leads", runId],
    queryFn: () => ok(client.GET("/api/runs/{run_id}/leads", path)),
    refetchInterval: live ? 3000 : false,
  });

  const calls = useQuery({
    queryKey: ["run-calls", runId],
    queryFn: () => ok(client.GET("/api/runs/{run_id}/calls", path)),
    refetchInterval: live ? 3000 : false,
  });
  const searches = useQuery({
    queryKey: ["run-searches", runId],
    queryFn: () => ok(client.GET("/api/runs/{run_id}/searches", path)),
    refetchInterval: live ? 3000 : false,
  });

  if (run.isPending) return <Skeleton rows={6} />;
  if (run.isError) return <Problem error={run.error} />;
  const data = run.data;
  const params = (data.params ?? {}) as Record<string, unknown>;
  const totals = totalsOf(data.counts);
  const discovery = discoveryLine(totals);
  const byStage = countsOf(data.counts);
  const stageRows = (STAGES as readonly string[]).filter((st) => st in byStage).map((st) => [st, byStage[st]!] as const);
  const outcomeColumns = ["advanced", "held", "failed", "waiting", "deferred", "suppressed", "skipped"].filter((o) => o === "advanced" || o === "held" || o === "failed" || stageRows.some(([, v]) => (v[o] ?? 0) > 0));

  return (
    <>
      <PageHeader
        crumbs={
          <>
            <Link to="/runs" className="hover:text-ink hover:underline">
              Runs
            </Link>{" "}
            / <span className="text-ink">Run from {ago(data.started_at ?? data.created_at)}</span>
          </>
        }
        title="Run"
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <StatusBadge status={describe(runStatus, data.status)} />
            <span>Started {when(data.started_at) || "not yet"}</span>
            {data.finished_at && <span>Finished {when(data.finished_at)}</span>}
            <span>Spend {usd(data.cost_micro_usd)}</span>
            <span className="font-mono text-muted">{data.id}</span>
          </span>
        }
      />

      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5" data-tour="run-numbers">
        <Stat label="Took" value={data.started_at ? duration(data.started_at, data.finished_at) : "—"} hint={live ? "still going" : data.finished_at ? `finished ${ago(data.finished_at)}` : undefined} />
        <Stat label="Steps completed" value={totals.moved} hint={`${totals.newLeads} new lead${totals.newLeads === 1 ? "" : "s"} found`} tone="good" />
        <Stat label="Held" value={totals.held} hint={totals.held ? "waiting on you or a rule" : "none"} tone={totals.held ? "attention" : undefined} />
        <Stat label="Failed" value={totals.failed} hint={totals.failed ? "see the list below" : "none"} tone={totals.failed ? "error" : undefined} />
        <Stat label="Spend" value={usd(data.cost_micro_usd)} hint={totals.moved ? `${usd(data.cost_micro_usd / totals.moved)} per step completed` : "no paid calls"} />
      </div>

      {(totals.failed > 0 || data.status === "failed") && (
        <Callout tone="error" title={data.status === "failed" ? "This run failed" : `${totals.failed} step${totals.failed === 1 ? "" : "s"} failed`} className="mb-5">
          The leads that failed are listed first below, each with the reason. A failed lead is tried again by the next run, or press Retry on its page.
        </Callout>
      )}
      {discovery && (
        <Callout tone={totals.newLeads === 0 ? "attention" : "good"} title="Discovery" className="mb-5">
          {discovery}
        </Callout>
      )}

      <Card tour="run-summary" title="Step by step" subtitle={Object.keys(params).length ? `Asked for: ${Object.entries(params).map(([k, v]) => `${words(k)} ${Array.isArray(v) ? v.join(", ") || "all" : String(v)}`).join(" · ")}` : "Every step, over all the work that was due."} className="mb-5">
        {stageRows.length === 0 ? (
          <p className="text-xs text-muted">{live ? "No step has finished yet." : "Nothing was due, so no step had anything to do."}</p>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Step</Th>
                {outcomeColumns.map((o) => (
                  <Th key={o} className="text-right">
                    {OUTCOME_LABEL[o] ?? o}
                  </Th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stageRows.map(([stage, outcomes]) => (
                <tr key={stage}>
                  <Td className="font-medium">{STAGE_LABEL[stage] ?? words(stage)}</Td>
                  {outcomeColumns.map((o) => (
                    <Td key={o} className={cx("text-right font-mono text-xs", !outcomes[o] && "text-muted", o === "failed" && outcomes[o] ? "font-semibold text-error" : "")}>
                      {outcomes[o] ?? 0}
                    </Td>
                  ))}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {live && <p className="mt-3 text-xs text-muted">This run is still going; the numbers and the list below fill in as it works.</p>}
      </Card>

      {(searches.data?.length ?? 0) > 0 && (
        <Card tour="run-searches" title="What it searched for" subtitle="Each run looks from a new angle, so it finds companies the earlier ones did not." className="mb-5">
          <ul className="divide-y divide-line text-[13px]">
            {searches.data!.map((q, i) => (
              <li key={i} className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
                <span className="min-w-0 flex-1">{q.query}</span>
                <span className="whitespace-nowrap text-xs text-muted">
                  <strong className={cx("font-semibold", q.new_leads > 0 ? "text-good" : "text-muted")}>{q.new_leads} new</strong>
                  {q.already_leads > 0 && ` · ${q.already_leads} already yours`}
                </span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card tour="run-calls" title="What it spent, by vendor" subtitle="Every vendor call this run made. Reused answers cost nothing." className="mb-5">
        <QueryState query={calls}>
          {(rows) =>
            rows.length === 0 ? (
              <p className="text-xs text-muted">No vendor was called in this run.</p>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Vendor</Th>
                    <Th>For</Th>
                    <Th className="text-right">Calls</Th>
                    <Th className="text-right">Found</Th>
                    <Th className="text-right">Nothing</Th>
                    <Th className="text-right">Reused</Th>
                    <Th className="text-right">Errors</Th>
                    <Th className="text-right">Avg time</Th>
                    <Th className="text-right">Cost</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={`${c.provider}:${c.operation}`}>
                      <Td className="font-medium">{c.provider}</Td>
                      <Td className="text-muted">{words(c.operation)}</Td>
                      <Td className="text-right font-mono text-xs">{c.calls}</Td>
                      <Td className="text-right font-mono text-xs">{c.found}</Td>
                      <Td className="text-right font-mono text-xs">{c.nothing}</Td>
                      <Td className="text-right font-mono text-xs">{c.reused}</Td>
                      <Td className={cx("text-right font-mono text-xs", c.errors > 0 && "font-semibold text-error")}>{c.errors}{c.blocked ? ` (+${c.blocked} blocked)` : ""}</Td>
                      <Td className="text-right font-mono text-xs text-muted">{c.avg_latency_ms == null ? "–" : `${c.avg_latency_ms} ms`}</Td>
                      <Td className="text-right font-mono text-xs">{usd(c.cost_micro_usd)}</Td>
                    </tr>
                  ))}
                  <tr className="border-t border-line font-semibold">
                    <Td>Total</Td>
                    <Td />
                    <Td className="text-right font-mono text-xs">{rows.reduce((n, c) => n + c.calls, 0)}</Td>
                    <Td colSpan={5} />
                    <Td className="text-right font-mono text-xs">{usd(rows.reduce((n, c) => n + c.cost_micro_usd, 0))}</Td>
                  </tr>
                </tbody>
              </Table>
            )
          }
        </QueryState>
      </Card>

      <Card tour="run-leads" title="Leads this run touched" subtitle="Each lead it moved on, held, failed or will retry, with every step. Click a lead to open it." className="p-0 [&>header]:px-4 [&>header]:pt-4">
        <QueryState query={leads}>
          {(rows) =>
            rows.length === 0 ? (
              <Empty title={live ? "Nothing yet" : "No lead changed"}>{live ? "Leads appear here as the run moves them." : "This run found nothing due, or left every lead where it was."}</Empty>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Lead</Th>
                    <Th>Result</Th>
                    <Th>What happened</Th>
                    <Th>Now</Th>
                  </tr>
                </thead>
                <tbody>
                  {[...rows].sort((a, b) => ORDER.indexOf(a.outcome) - ORDER.indexOf(b.outcome)).map((lead) => (
                    <LeadRow key={lead.company_id} lead={lead} />
                  ))}
                </tbody>
              </Table>
            )
          }
        </QueryState>
      </Card>
    </>
  );
}

function LeadRow({ lead }: { lead: Lead }) {
  const outcome = OUTCOME[lead.outcome] ?? OUTCOME.moved;
  return (
    <tr className="align-top hover:bg-surface-low">
      <Td>
        <Link to="/leads/$companyId" params={{ companyId: lead.company_id }} className="font-semibold text-primary hover:underline">
          {lead.name ?? lead.domain}
        </Link>
        <div className="font-mono text-[11px] text-muted">{lead.domain}</div>
      </Td>
      <Td>
        <span className={cx("rounded-full px-2 py-0.5 text-[11px] font-medium", outcome.tone)}>{outcome.label}</span>
      </Td>
      <Td>
        <ol className="space-y-0.5 text-xs">
          {lead.steps.map((step, i) => (
            <li key={i} className="flex flex-wrap items-center gap-1">
              {step.kind === "deferred" ? (
                <span className="text-muted">put off</span>
              ) : (
                <>
                  <span>{describe(leadStatus, step.from_status ?? "").label}</span>
                  <ArrowRight className="size-3 text-muted" aria-hidden />
                  <span className="font-medium">{describe(leadStatus, step.to_status ?? "").label}</span>
                </>
              )}
              {step.detail && <span className="text-muted">· {step.detail}</span>}
            </li>
          ))}
        </ol>
      </Td>
      <Td className="whitespace-nowrap">
        <StatusBadge status={describe(leadStatus, lead.status)} />
        <div className="mt-1">
          <Link to="/leads/$companyId/journey" params={{ companyId: lead.company_id }} className={buttonClass("ghost", "sm")}>
            Journey
          </Link>
        </div>
      </Td>
    </tr>
  );
}
