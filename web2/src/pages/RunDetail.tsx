import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { client, ok, type Schemas } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Card, Empty, PageHeader, Problem, QueryState, Skeleton, Table, Td, Th, buttonClass } from "../components/ui";
import { cx } from "../lib/cx";
import { ago, usd, when, words } from "../lib/format";
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

  if (run.isPending) return <Skeleton rows={6} />;
  if (run.isError) return <Problem error={run.error} />;
  const data = run.data;
  const params = (data.params ?? {}) as Record<string, unknown>;
  const counts = Object.entries((data.counts ?? {}) as Record<string, Record<string, number>>).filter(([, v]) => v && typeof v === "object");

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

      <Card tour="run-summary" title="What it was asked to do" className="mb-5">
        <p className="text-xs text-muted">
          {Object.entries(params)
            .map(([k, v]) => `${words(k)}: ${Array.isArray(v) ? v.join(", ") || "all" : String(v)}`)
            .join(" · ") || "Every step, over all the work that was due."}
        </p>
        {counts.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {counts.map(([stage, outcomes]) => (
              <span key={stage} className="rounded-lg border border-line px-2 py-1 text-xs">
                <strong className="font-semibold">{words(stage)}</strong>{" "}
                {Object.entries(outcomes)
                  .map(([outcome, n]) => `${n} ${outcome}`)
                  .join(", ")}
              </span>
            ))}
          </div>
        )}
        {live && <p className="mt-3 text-xs text-muted">This run is still going; the list below fills in as it works.</p>}
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
