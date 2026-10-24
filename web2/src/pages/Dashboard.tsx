import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Play, Workflow } from "lucide-react";
import type { ReactNode } from "react";
import { client, ok } from "../api/client";
import { useCurrent } from "../app/session";
import { StatusBadge } from "../components/StatusBadge";
import { Card, Label, PageHeader, Skeleton, buttonClass } from "../components/ui";
import { cx } from "../lib/cx";
import { ago, duration, percent, usd } from "../lib/format";
import { useSetup } from "../lib/setup";
import { describe, describeHold, leadStatus, runStatus } from "../lib/status";

/** The main path, left to right. Each stage counts the leads whose status is that stage's. */
const FUNNEL = [
  { key: "new", label: "Intake", note: "waiting for research" },
  { key: "researched", label: "Research", note: "waiting for the gate" },
  { key: "qualified", label: "Qualification", note: "passed fit and country" },
  { key: "contacts_found", label: "People", note: "people ranked" },
  { key: "email_ready", label: "Email address", note: "safe address found" },
  { key: "copy_ready", label: "Review", note: "waiting for you", gate: true },
  { key: "approved", label: "Approved", note: "drafted on the next run" },
  { key: "in_sequence", label: "Drafted", note: "in your mailbox" },
] as const;

const SIDE_EXITS = ["held", "disqualified", "failed", "rejected", "suppressed"] as const;

export function DashboardPage() {
  const status = useQuery({ queryKey: ["status"], queryFn: () => ok(client.GET("/api/status")), refetchInterval: 5000 });
  const waiting = useQuery({ queryKey: ["waiting"], queryFn: () => ok(client.GET("/api/targets/waiting")) });
  const quality = useQuery({ queryKey: ["quality"], queryFn: () => ok(client.GET("/api/reports/quality")) });
  const cost = useQuery({ queryKey: ["cost", 30], queryFn: () => ok(client.GET("/api/reports/cost", { params: { query: { days: 30 } } })) });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => ok(client.GET("/api/runs")) });
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });

  const by = status.data?.by_status ?? {};
  const held = status.data?.held ?? {};
  const heldTotal = Object.values(held).reduce((sum, n) => sum + n, 0);
  const toReview = status.data?.waiting_for_review ?? 0;
  const failed = by.failed ?? 0;
  const toConfirm = waiting.data?.length ?? 0;
  const inPipeline = FUNNEL.reduce((sum, stage) => sum + (by[stage.key] ?? 0), 0);
  const total = Object.values(by).reduce((sum, n) => sum + n, 0);
  const widest = Math.max(1, ...FUNNEL.map((stage) => by[stage.key] ?? 0));
  const latest = runs.data?.[0];
  const ceiling = settings.data?.budget_per_prospect_micro_usd as number | null | undefined;

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={status.isSuccess ? `${total} companies · ${inPipeline} on the main path · ${toReview + heldTotal + failed + toConfirm} items need you` : "Loading…"}
        actions={
          <Link to="/runs" className={buttonClass("primary")}>
            <Play className="size-3.5 fill-current" aria-hidden /> Start a run
          </Link>
        }
      />

      <GetStarted />

      <Label className="mb-2">Needs you</Label>
      <div data-tour="needs-you" className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <NeedCard count={toReview} label="Emails to review" detail="Written and checked; nothing is drafted until you approve." to="/review" action="Review emails" tone="attention" />
        <NeedCard
          count={heldTotal}
          label="Leads on hold"
          detail={heldTotal ? Object.entries(held).map(([reason, n]) => `${describeHold(reason).label} ${n}`).join(" · ") : "No lead is waiting on a decision."}
          to="/attention"
          action="Resolve holds"
          tone="attention"
        />
        <NeedCard count={failed} label="Failed leads" detail="A step failed; each lead shows the step and the reason." to="/attention" action="See failures" tone="error" />
        <NeedCard count={toConfirm} label="Websites to confirm" detail="Added by name; the website found is not certain." to="/attention" action="Confirm websites" tone="attention" />
      </div>

      <section data-tour="pipeline" className="relative mb-6 overflow-hidden rounded-xl border border-line bg-surface p-5">
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary via-primary-container to-good" aria-hidden />
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2.5">
            <span className="flex size-7 items-center justify-center rounded-lg bg-primary-fixed text-primary">
              <Workflow className="size-4" aria-hidden />
            </span>
            <h2 className="text-lg font-semibold tracking-tight">Pipeline</h2>
            <span className="rounded-full border border-line bg-surface-low px-2.5 py-0.5 font-mono text-xs">{inPipeline} on the main path</span>
          </div>
          <Link to="/leads" className="text-xs font-semibold text-primary hover:underline">
            All leads
          </Link>
        </div>

        {status.isPending ? (
          <Skeleton rows={3} />
        ) : (
          <div className="overflow-x-auto pb-1">
            <ol className="grid min-w-[880px] grid-cols-8 gap-2">
              {FUNNEL.map((stage, index) => {
                const count = by[stage.key] ?? 0;
                const gate = "gate" in stage;
                return (
                  <li key={stage.key}>
                    <Link
                      to={gate ? "/review" : "/leads"}
                      search={gate ? undefined : { status: stage.key }}
                      className={cx(
                        "flex h-full flex-col rounded-lg border p-3 transition-colors",
                        gate && count > 0 ? "border-attention bg-attention-container/40 hover:bg-attention-container/70" : "border-line hover:border-primary-container/60 hover:bg-surface-low",
                      )}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[11px] text-muted">{String(index + 1).padStart(2, "0")}</span>
                        {gate && <span className="rounded bg-attention px-1 text-[9px] font-bold uppercase tracking-wider text-white">You</span>}
                      </div>
                      <div className="mt-1 truncate text-xs font-semibold">{stage.label}</div>
                      <div className="mt-1 font-mono text-xl font-semibold">{count}</div>
                      <div className="mt-0.5 truncate text-[11px] text-muted" title={stage.note}>
                        {stage.note}
                      </div>
                      <div className="mt-2 h-1 rounded-full bg-surface-container">
                        <div className={cx("h-1 rounded-full", gate ? "bg-attention" : "bg-primary-container")} style={{ width: `${(count / widest) * 100}%` }} />
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ol>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="mr-1 text-[11px] font-semibold uppercase tracking-wider text-muted">Left the main path</span>
          {SIDE_EXITS.map((key) => (
            <Link key={key} to="/leads" search={{ status: key }} className="inline-flex items-center gap-1.5 rounded-lg border border-line px-1.5 py-1 hover:bg-surface-low">
              <StatusBadge status={describe(leadStatus, key)} />
              <span className="font-mono text-xs font-semibold">{by[key] ?? 0}</span>
            </Link>
          ))}
          {(by.replied ?? 0) + (by.completed ?? 0) > 0 && (
            <span className="text-xs text-muted">
              · {by.replied ?? 0} replied, {by.completed ?? 0} completed
            </span>
          )}
        </div>
      </section>

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        <Card title="Spend" subtitle="Last 30 days" actions={<Link to="/reports" className="text-xs font-semibold text-primary hover:underline">Reports</Link>}>
          {cost.isPending ? (
            <Skeleton />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 rounded-lg border border-line bg-surface-low p-3">
                <Metric label="Total" value={usd(cost.data?.total, 2)} hint={`${cost.data?.paid_calls ?? 0} paid calls`} />
                <Metric
                  label="Per prospect"
                  value={cost.data?.per_prospect != null ? usd(cost.data.per_prospect) : "–"}
                  hint={ceiling == null ? "No budget ceiling set" : `Ceiling ${usd(ceiling, 2)}`}
                  tone="primary"
                />
                {ceiling != null && ceiling > 0 && cost.data?.per_prospect != null && <BudgetMeter spent={cost.data.per_prospect} ceiling={ceiling} />}
              </div>
              <Label className="mb-2 mt-4">By vendor</Label>
              <ProviderBars byProvider={cost.data?.by_provider ?? {}} calls={cost.data?.calls_by_provider ?? {}} total={cost.data?.total ?? 0} />
            </>
          )}
        </Card>

        <div className="space-y-6">
          <Card title="Quality" subtitle="Of the first emails you sent">
            {quality.isPending ? (
              <Skeleton />
            ) : (
              <>
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="font-mono text-[28px] font-semibold">{percent(quality.data?.unedited_share)}</span>
                  <span className="text-xs text-muted">went out without an edit · target 80%</span>
                </div>
                {quality.data?.sent === 0 && <p className="mt-1 text-xs text-muted">Nothing has been sent yet; this fills in once the Sent folder is read.</p>}
                <dl className="mt-3 grid grid-cols-2 gap-2 border-t border-line pt-3 text-xs">
                  <Pair label="Written" value={quality.data?.written ?? 0} />
                  <Pair label="Sent" value={quality.data?.sent ?? 0} />
                  <Pair label="Flagged by the checks" value={percent(quality.data?.flag_rate)} />
                  <Pair label="Catch-all addresses" value={percent(quality.data?.catch_all_share)} />
                </dl>
              </>
            )}
          </Card>

          <Card title="Engine activity" actions={<Link to="/runs" className="text-xs font-semibold text-primary hover:underline">All runs</Link>}>
            {runs.isPending ? (
              <Skeleton rows={2} />
            ) : latest ? (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2.5">
                  <StatusBadge status={describe(runStatus, latest.status)} />
                  <span className="text-xs text-muted">
                    started {ago(latest.started_at ?? latest.created_at)}
                    {latest.started_at && ` · took ${duration(latest.started_at, latest.finished_at)}`}
                  </span>
                  <span className="ml-auto font-mono text-xs">{usd(latest.cost_micro_usd)}</span>
                </div>
                <RunCounts counts={latest.counts} />
              </div>
            ) : (
              <p className="text-xs text-muted">No runs yet. Add a target, then start a run.</p>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

function NeedCard({ count, label, detail, to, action, tone }: { count: number; label: string; detail: string; to: string; action: string; tone: "attention" | "error" }) {
  const live = count > 0;
  return (
    <div className={cx("group flex flex-col rounded-xl border p-4 transition-colors", live ? (tone === "error" ? "border-error/40 bg-surface" : "border-attention/50 bg-attention-container/25") : "border-line bg-surface")}>
      <div className={cx("font-mono text-[28px] font-semibold leading-9", live ? (tone === "error" ? "text-error" : "text-attention") : "text-muted")}>{count}</div>
      <div className="text-[13px] font-semibold">{label}</div>
      <p className="mt-0.5 line-clamp-2 min-h-8 text-xs text-muted" title={detail}>
        {detail}
      </p>
      <Link to={to} className="mt-3 flex items-center justify-between border-t border-line pt-2 text-xs font-semibold text-primary hover:underline">
        {live ? action : "Open"}
        <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </Link>
    </div>
  );
}

function Metric({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "primary" }) {
  return (
    <div>
      <Label>{label}</Label>
      <div className={cx("mt-0.5 font-mono text-2xl font-semibold", tone === "primary" && "text-primary")}>{value}</div>
      {hint && <div className="font-mono text-[11px] text-muted">{hint}</div>}
    </div>
  );
}

function Pair({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-muted">{label}</dt>
      <dd className="font-mono font-semibold">{value}</dd>
    </div>
  );
}

/** Average spend per prospect against the ceiling. Over 70% turns amber, over 90% red. */
export function BudgetMeter({ spent, ceiling }: { spent: number; ceiling: number }) {
  const used = Math.min(100, Math.round((spent / ceiling) * 100));
  return (
    <div className="col-span-2">
      <div className="mb-1 flex justify-between font-mono text-[11px] text-muted">
        <span>Average spend against the ceiling</span>
        <span className={cx("font-semibold", used > 90 ? "text-error" : used > 70 ? "text-attention" : "text-good")}>{used}% used</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-container" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={used} aria-label="Budget used">
        <div className={cx("h-full rounded-full", used > 90 ? "bg-error" : used > 70 ? "bg-attention" : "bg-primary-container")} style={{ width: `${Math.max(2, used)}%` }} />
      </div>
    </div>
  );
}

export function ProviderBars({ byProvider, calls, total }: { byProvider: Record<string, number>; calls: Record<string, number>; total: number }) {
  const rows = Object.keys({ ...calls, ...byProvider }).sort((a, b) => (byProvider[b] ?? 0) - (byProvider[a] ?? 0) || (calls[b] ?? 0) - (calls[a] ?? 0));
  if (rows.length === 0) return <p className="text-xs text-muted">No vendor calls recorded yet.</p>;
  return (
    <ul className="space-y-2">
      {rows.map((vendor) => {
        const micro = byProvider[vendor] ?? 0;
        const share = total > 0 ? Math.round((micro / total) * 100) : 0;
        return (
          <li key={vendor}>
            <div className="flex items-center justify-between gap-2 font-mono text-xs">
              <span className="font-medium">{vendor}</span>
              <span className="text-muted">
                {calls[vendor] ?? 0} calls · {usd(micro)} {total > 0 && `(${share}%)`}
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-container">
              <div className="h-full bg-primary-container" style={{ width: `${share}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** A run's counts, per stage: "research 6 advanced · gate 5 advanced, 1 held". */
export function RunCounts({ counts }: { counts: Record<string, unknown> | null | undefined }) {
  const stages = Object.entries(counts ?? {}).filter(([, value]) => typeof value === "object" && value && Object.keys(value).length > 0) as [string, Record<string, number>][];
  if (stages.length === 0) return <p className="text-xs text-muted">No lead moved in this run.</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {stages.map(([stage, outcome]) => (
        <li key={stage} className="rounded-md border border-line bg-surface-low px-2 py-0.5 text-[11px]">
          <span className="font-semibold">{stage}</span>{" "}
          <span className="text-muted">
            {Object.entries(outcome)
              .map(([kind, n]) => `${n} ${kind}`)
              .join(", ")}
          </span>
        </li>
      ))}
    </ul>
  );
}


/** Until every required step is done, the dashboard leads with what is left. */
function GetStarted() {
  const { workspace } = useCurrent();
  const setup = useSetup();
  if (!setup.data || setup.data.done || workspace.role !== "admin") return null;
  const left = setup.data.items.filter((i) => i.status === "missing");
  return (
    <Card tour="get-started" className="mb-6" tone="attention" title="Get started" subtitle={`${left.length} thing${left.length === 1 ? "" : "s"} to do before the engine can draft your first email.`}>
      <div className="flex flex-wrap items-center justify-between gap-3 text-[13px]">
        <span>
          Next: <strong>{setup.data.next?.title}</strong>
        </span>
        <Link to="/onboarding" className={buttonClass("primary")}>
          Continue setup
        </Link>
      </div>
    </Card>
  );
}
