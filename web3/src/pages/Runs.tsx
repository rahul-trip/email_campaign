import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square } from "lucide-react";
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { client, ok } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Button, Callout, Card, Empty, PageHeader, Problem, QueryState, Stat, Table, Td, Th, buttonClass, StartNow } from "../ui/compat";
import { Chip, Segmented, Toggle } from "../ui/core";
import { Drawer, useToast } from "../ui/overlay";
import { cx } from "../lib/cx";
import { percent } from "../lib/format";
import { ago, duration, usd, when } from "../lib/format";
import { describe, runStatus } from "../lib/status";
import { useUsage } from "../lib/usage";
import { STAGES, STAGE_LABEL, countsOf, discoveryLine, stagesDone, totalsOf } from "../lib/runs";

type Mode = "manual" | "discovery" | "mixed";
const MODES: [Mode, string, string][] = [
  ["manual", "Only the leads I added", "Moves the companies you added as far as each can go."],
  ["discovery", "Discover new companies", "Searches the web for companies matching the campaign's ideal customer, then moves them on."],
  ["mixed", "My leads and discovery", "Both of the above in one run."],
];
const WORKER_SILENT_MS = 45_000;

export function RunsPage() {
  const queryClient = useQueryClient();
  const [drawer, setDrawer] = useState(false);
  const [fresh, setFresh] = useState<string | null>(null);
  const toast = useToast();
  const usage = useUsage();
  const canSkip = usage.data?.features.includes("directory_bypass") ?? false;

  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => ok(client.GET("/api/runs")),
    // Poll quickly while anything is queued or running, so progress and spend update live.
    refetchInterval: (query) => (query.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2000 : 10000),
  });
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  const ceiling = settings.data?.budget_per_prospect_micro_usd as number | null | undefined;

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["runs"] });
  const cancel = useMutation({ mutationFn: (id: string) => ok(client.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: id } } })), onSuccess: refresh });

  const queuedTooLong = runs.data?.some((r) => r.status === "queued" && Date.now() - new Date(r.created_at).getTime() > WORKER_SILENT_MS);
  const busy = runs.data?.some((r) => r.status === "queued" || r.status === "running");

  return (
    <>
      <PageHeader
        title="Discovery runs"
        subtitle="A run moves every company that is due as far as it can go, step by step, and records what it spent."
        actions={
          <Button data-tour="start-run" onClick={() => setDrawer(true)}>
            <Play className="size-4 fill-current" aria-hidden /> Start a run now
          </Button>
        }
      />
      {drawer && (
        <StartRunDrawer
          canSkip={canSkip}
          campaign={(campaigns.data ?? []).find((c) => c.status === "active")?.name}
          ceiling={ceiling}
          busy={!!busy && !queuedTooLong}
          onClose={() => setDrawer(false)}
          onStarted={(id) => {
            setDrawer(false);
            setFresh(id);
            refresh();
            toast({ tone: "good", title: "Run started", body: "We'll show what it finds here as it goes.", action: { label: "Cancel run", onClick: () => cancel.mutate(id) } });
          }}
        />
      )}
      <Problem error={cancel.error} className="mb-3" />

      <RunStats runs={runs.data ?? []} />
      <AutoDiscoveryLine />

      {queuedTooLong && (
        <Callout tone="error" title="Nothing is picking up queued runs" className="mb-5">
          The worker is probably not running. Start it in a terminal with <code className="font-mono">uv run outbound worker</code>.
        </Callout>
      )}

      <Card tour="recent-runs" title="Recent runs" className="p-0">
        <QueryState query={runs} shape="table">
          {(rows) =>
            rows.length === 0 ? (
              <Empty title="No runs yet" action={<StartNow label="Start your first run" />}>A run researches your leads and writes the first drafts. Add leads first, then start one.</Empty>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Started</Th>
                    <Th>State</Th>
                    <Th>What it did</Th>
                    <Th className="hidden md:table-cell">Took</Th>
                    <Th className="text-right">Spend</Th>
                    <Th>
                      <span className="sr-only">Actions</span>
                    </Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((run) => {
                    const live = run.status === "queued" || run.status === "running";
                    const params = (run.params ?? {}) as { mode?: string; campaign?: string; discover?: number; limit?: number };
                    return (
                      <tr key={run.id} className={cx("align-top hover:bg-surface-2", run.id === fresh && "bg-primary-soft outline outline-2 -outline-offset-2 outline-primary")}>
                        <Td className="whitespace-nowrap">
                          <Link to="/runs/$runId" params={{ runId: run.id }} className="text-body font-semibold text-primary hover:underline">
                            {ago(run.started_at ?? run.created_at)}
                          </Link>
                          {run.id === fresh && <Chip tone="primary" className="ml-2 animate-pop">New</Chip>}
                          <div className="text-label text-muted" title={when(run.created_at)}>
                            {MODES.find(([m]) => m === params.mode)?.[1] ?? run.kind}
                          </div>
                        </Td>
                        <Td>
                          <StatusBadge status={describe(runStatus, run.status)} />
                        </Td>
                        <Td>
                          <RunSummary run={run} />
                        </Td>
                        <Td className="hidden whitespace-nowrap text-small text-muted md:table-cell">{run.started_at ? duration(run.started_at, run.finished_at) : "not started"}</Td>
                        <Td className="tnum text-right text-small">{usd(run.cost_micro_usd)}</Td>
                        <Td className="whitespace-nowrap text-right">
                          {live && (
                            <Button variant="danger-ghost" size="sm" busy={cancel.isPending && cancel.variables === run.id} onClick={() => cancel.mutate(run.id)}>
                              <Square className="size-3" aria-hidden /> Cancel
                            </Button>
                          )}
                          <Link to="/runs/$runId" params={{ runId: run.id }} className={buttonClass("ghost", "sm")}>
                            Open
                          </Link>
                        </Td>
                      </tr>
                    );
                  })}
                </tbody>
              </Table>
            )
          }
        </QueryState>
      </Card>
    </>
  );
}


const DAY = 24 * 60 * 60 * 1000;

/** The week at a glance, from the recent runs. */
function RunStats({ runs }: { runs: Run[] }) {
  const week = runs.filter((r) => Date.now() - new Date(r.started_at ?? r.created_at).getTime() < 7 * DAY && r.status !== "cancelled");
  if (runs.length === 0) return null;
  const totals = week.map((r) => totalsOf(r.counts));
  const sum = (pick: (t: ReturnType<typeof totalsOf>) => number) => totals.reduce((n, t) => n + pick(t), 0);
  const moved = sum((t) => t.moved);
  const attention = sum((t) => t.held + t.failed);
  const spend = week.reduce((n, r) => n + r.cost_micro_usd, 0);
  const failedRuns = week.filter((r) => r.status === "failed").length;
  return (
    <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-5" data-tour="run-stats">
      <Stat label="Runs this week" value={week.length} hint={failedRuns ? `${failedRuns} failed` : "none failed"} tone={failedRuns ? "error" : undefined} />
      <Stat label="Steps completed" value={moved} hint="leads moved on, step by step" tone="good" />
      <Stat label="New leads found" value={sum((t) => t.newLeads)} hint={`${sum((t) => t.alreadyLeads)} were already yours`} />
      <Stat label="Held or failed" value={attention} hint={attention ? "see Needs attention" : "nothing stuck"} tone={attention ? "attention" : undefined} />
      <Stat label="Spend this week" value={usd(spend)} hint={moved ? `${usd(spend / moved)} per step completed` : "no paid calls"} />
    </div>
  );
}

type Run = NonNullable<ReturnType<typeof useRunsData>["data"]>[number];
const useRunsData = () => useQuery({ queryKey: ["runs"], queryFn: () => ok(client.GET("/api/runs")) });

/** What a run did, in words: results first, then what each step did, and how far a live run has got. */
function RunSummary({ run }: { run: Run }) {
  const totals = totalsOf(run.counts);
  const counts = countsOf(run.counts);
  const live = run.status === "queued" || run.status === "running";
  const line = discoveryLine(totals);
  const done = stagesDone(run.counts);
  const chips: [string, number, string][] = [
    ["moved on", totals.moved, "bg-good-soft text-good"],
    ["held", totals.held, "bg-attention-soft text-attention"],
    ["failed", totals.failed, "bg-error-soft text-error"],
    ["will retry", totals.retry, "bg-surface-3 text-muted"],
    ["waiting for credits", totals.waiting, "bg-attention-soft text-attention"],
  ];
  const shown = chips.filter(([, n]) => n > 0);
  return (
    <div className="space-y-1.5">
      {live && (
        <div>
          <div className="text-label text-muted">{run.status === "queued" ? "Waiting for the worker" : `Step ${Math.min(done + 1, STAGES.length)} of ${STAGES.length}: ${STAGE_LABEL[STAGES[Math.min(done, STAGES.length - 1)]!]}`}</div>
          <div className="mt-1 h-1.5 w-40 overflow-hidden rounded-full bg-surface-3" role="progressbar" aria-valuenow={done} aria-valuemin={0} aria-valuemax={STAGES.length}>
            <div className="h-full rounded-full bg-primary transition-all" style={{ width: `${(done / STAGES.length) * 100}%` }} />
          </div>
        </div>
      )}
      {shown.length > 0 ? (
        <ul className="flex flex-wrap gap-1">
          {shown.map(([label, n, tone]) => (
            <li key={label} className={`rounded-full px-2 py-0.5 text-label font-medium ${tone}`}>
              {n} {label}
            </li>
          ))}
        </ul>
      ) : !live ? (
        <p className="text-small text-muted">{run.status === "cancelled" ? "Cancelled before it moved anything." : Object.keys(counts).length ? "Nothing was due, so nothing moved." : "Nothing recorded."}</p>
      ) : null}
      {line && <p className={`text-label ${totals.newLeads === 0 ? "text-attention" : "text-muted"}`}>{line}</p>}
    </div>
  );
}

const clock = (iso: string) => new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** Whether the worker searches for new companies by itself, when it next will, or why it is not. */
function AutoDiscoveryLine() {
  const state = useQuery({ queryKey: ["auto-discovery"], queryFn: () => ok(client.GET("/api/runs/auto-discovery")), refetchInterval: 30000 });
  const d = state.data;
  if (!d) return null;
  const every = `about every ${Math.round(24 / d.per_day)} hours`;
  const why: Record<string, string> = {
    off: "Automatic discovery is switched off (Settings, Limits).",
    no_campaign: "Automatic discovery waits for an active campaign that says who it is after.",
    no_credits: "Automatic discovery is paused: no discovery credits are left.",
    run_in_progress: "A run is in progress; the next search waits for it.",
    review_full: `Automatic discovery is paused: Review holds ${d.waiting_for_review} drafts. It resumes below ${d.review_limit}.`,
    backlog: "Automatic discovery waits while the leads already found are being worked on.",
  };
  const text = d.reason == null || d.reason === "not_yet" ? `Automatic discovery is on, ${every}.${d.next_search ? ` Next search around ${clock(d.next_search)}.` : " The next search starts on the next pass."}` : why[d.reason];
  const paused = d.reason !== null && d.reason !== "not_yet" && d.reason !== "run_in_progress";
  return (
    <div data-tour="auto-discovery">
      <Callout tone={paused ? "attention" : "info"} className="mb-5">
        {text}
      </Callout>
    </div>
  );
}

const SOURCE_LABEL: Record<string, string> = { yc_directory: "YC directory", companies_house: "Companies House", exa: "Exa", articles: "Web lists" };

/** The start-run slide-over: what to run, how many companies to find (1–50, as the API takes),
 * the sources the brief will use (chosen by the engine, shown read-only), and the one switch the
 * plan allows. Sends exactly what web2's form sent. */
function StartRunDrawer({ canSkip, campaign, ceiling, busy, onClose, onStarted }: { canSkip: boolean; campaign?: string; ceiling?: number | null; busy: boolean; onClose: () => void; onStarted: (id: string) => void }) {
  const [mode, setMode] = useState<Mode>("manual");
  const [discover, setDiscover] = useState(25);
  const [skipDirectory, setSkipDirectory] = useState(false);
  const plan = useQuery({ queryKey: ["run-plan"], queryFn: () => ok(client.GET("/api/runs/plan")) });
  const start = useMutation({
    mutationFn: () => ok(client.POST("/api/runs", { body: { mode, discover, ...(canSkip && skipDirectory ? { skip_directory: true } : {}) } })),
    onSuccess: (run) => onStarted(run.id),
  });
  const searching = mode !== "manual";
  const suited = (plan.data?.sources ?? []).filter((s) => s.suited);
  const rated = suited.filter((s) => s.rate != null);
  const rate = rated.length ? rated.reduce((a, s) => a + (s.rate ?? 0), 0) / rated.length : null;
  return (
    <Drawer
      title="Start a run"
      subtitle={campaign ? `Looks for companies that fit “${campaign}”` : "No campaign is active: only the leads you added can move."}
      onClose={onClose}
      footer={
        <div className="space-y-3">
          {searching && (
            <div className="rounded-xl bg-primary-soft px-3 py-2 text-small text-ink-2">
              ≈ {discover} companies named{rate != null ? ` · about ${Math.max(1, Math.round(discover * rate))} likely fits (from your ${percent(rate)} recent pass rate)` : ""} · a discovery credit only for each fit
            </div>
          )}
          {busy && <p className="text-small text-muted">A run is already queued or running; this one waits for it.</p>}
          <Problem error={start.error} />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button busy={start.isPending} onClick={() => start.mutate()}>
              <Play className="size-4 fill-current" aria-hidden /> Start run
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-7">
        <section>
          <div className="mb-2 text-body font-semibold text-ink">What to run</div>
          <div className="space-y-2">
            {MODES.map(([value, label, hint]) => (
              <label key={value} className={cx("press flex cursor-pointer gap-3 rounded-xl border p-3", mode === value ? "border-primary bg-primary-soft" : "border-line hover:border-line-strong")}>
                <input type="radio" name="mode" className="mt-1 accent-[var(--primary)]" checked={mode === value} onChange={() => setMode(value)} />
                <span>
                  <span className="block font-semibold text-ink">{label}</span>
                  <span className="block text-small text-muted">{hint}</span>
                </span>
              </label>
            ))}
          </div>
        </section>
        {searching && (
          <>
            <section>
              <div className="mb-2 text-body font-semibold text-ink">How many companies to find</div>
              <Segmented label="Companies to find" value={discover} onChange={setDiscover} options={[[10, "10"], [25, "25"], [50, "50"]]} />
              <p className="mt-2 text-small text-muted">Up to 50 a run. Only companies that pass your brief become leads.</p>
            </section>
            <section>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-body font-semibold text-ink">Where it will look</span>
                <span className="text-label text-muted">chosen for your brief</span>
              </div>
              <ul className="space-y-2">
                {(plan.data?.sources ?? []).map((s) => (
                  <li key={s.source} className={cx("rounded-xl border border-line p-3", !s.suited && "opacity-55")}>
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-ink">{SOURCE_LABEL[s.source] ?? s.source}</span>
                      {s.rate != null ? <Chip tone="good">{percent(s.rate)} pass · 90 days</Chip> : s.suited ? <Chip>new</Chip> : null}
                    </div>
                    {s.suited ? (
                      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-surface-3" title={`Asked for ${s.share}× the usual amount`}>
                        <div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, s.share * 50)}%` }} />
                      </div>
                    ) : (
                      <div className="mt-1 text-small text-muted">Skipped: {s.why_not}</div>
                    )}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-small text-muted">
                A source whose key is not set is skipped when the run starts. To sharpen what it finds,{" "}
                <Link to="/campaigns" className="font-semibold text-primary hover:underline">
                  edit the brief in Campaigns
                </Link>
                .
              </p>
            </section>
          </>
        )}
        {canSkip && (
          <Toggle label="Find emails with the vendors, not the shared directory" hint="For the leads this run works on. Costs vendor credits; what they find still updates the directory." checked={skipDirectory} onChange={setSkipDirectory} />
        )}
        <p className="text-small text-muted">
          A run works on up to 50 leads at each step. Budget per lead: {ceiling == null ? "no limit" : usd(ceiling, 2)}; a lead that reaches it makes no more paid calls.
        </p>
      </div>
    </Drawer>
  );
}
