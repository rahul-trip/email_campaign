import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square } from "lucide-react";
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { client, ok } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Button, Callout, Card, Checkbox, Empty, Field, Input, PageHeader, Problem, QueryState, Select, Stat, Table, Td, Th, buttonClass } from "../ui/compat";
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
  const [mode, setMode] = useState<Mode>("manual");
  const [discover, setDiscover] = useState(10);
    const [skipDirectory, setSkipDirectory] = useState(false);
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
  const start = useMutation({
    mutationFn: () => ok(client.POST("/api/runs", { body: { mode, discover, ...(canSkip && skipDirectory ? { skip_directory: true } : {}) } })),
    onSuccess: refresh,
  });
  const cancel = useMutation({ mutationFn: (id: string) => ok(client.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: id } } })), onSuccess: refresh });

  const queuedTooLong = runs.data?.some((r) => r.status === "queued" && Date.now() - new Date(r.created_at).getTime() > WORKER_SILENT_MS);
  const busy = runs.data?.some((r) => r.status === "queued" || r.status === "running");

  return (
    <>
      <PageHeader title="Runs" subtitle="A run moves every company that is due as far as it can go, step by step, and records what it spent." />

      <RunStats runs={runs.data ?? []} />
      <AutoDiscoveryLine />

      <Card tour="start-run" title="Start a run" className="mb-5">
        <div className="grid gap-3 md:grid-cols-[1fr_auto_auto] md:items-end">
          <Field label="What to run" hint={MODES.find(([m]) => m === mode)?.[2]}>
            <Select value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
              {MODES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          {mode !== "manual" ? (
            <>
              <Field label="Companies to discover">
                <Input type="number" min={1} max={50} value={discover} onChange={(e) => setDiscover(Number(e.target.value))} className="w-28" />
              </Field>
              <Field label="Campaign to search for">
                <div className="flex h-8 items-center text-body font-medium">{(campaigns.data ?? []).find((c) => c.status === "active")?.name ?? "None active"}</div>
              </Field>
            </>
          ) : (
            <div className="hidden md:col-span-2 md:block" />
          )}
        </div>
        {canSkip && (
          <div className="mt-3">
            <Checkbox
              label="Find emails with the vendors, not the shared directory"
              hint="For the leads this run works on. Costs credits at the vendors; what they find still updates the directory."
              checked={skipDirectory}
              onChange={setSkipDirectory}
            />
          </div>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3">
          <Button busy={start.isPending} onClick={() => start.mutate()}>
            <Play className="size-3.5 fill-current" aria-hidden /> Start run
          </Button>
          <span className="text-small text-muted">
            A run works on up to 50 leads at each step; the rest wait for the next run. Runs are carried out by the worker process. Budget per prospect: {ceiling == null ? "no limit" : usd(ceiling, 2)}; a lead that reaches it makes no more paid calls.
          </span>
        </div>
        {busy && !queuedTooLong && <p className="mt-2 text-small text-muted">A run is already queued or running; a new one waits for it.</p>}
        <Problem error={start.error ?? cancel.error} className="mt-3" />
      </Card>

      {queuedTooLong && (
        <Callout tone="error" title="Nothing is picking up queued runs" className="mb-5">
          The worker is probably not running. Start it in a terminal with <code className="font-mono">uv run outbound worker</code>.
        </Callout>
      )}

      <Card tour="recent-runs" title="Recent runs" className="p-0">
        <QueryState query={runs}>
          {(rows) =>
            rows.length === 0 ? (
              <Empty title="No runs yet">Start a run above once you have added leads.</Empty>
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
                      <tr key={run.id} className="align-top hover:bg-surface-2">
                        <Td className="whitespace-nowrap">
                          <Link to="/runs/$runId" params={{ runId: run.id }} className="text-body font-semibold text-primary hover:underline">
                            {ago(run.started_at ?? run.created_at)}
                          </Link>
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
                        <Td className="text-right font-mono text-small">{usd(run.cost_micro_usd)}</Td>
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
