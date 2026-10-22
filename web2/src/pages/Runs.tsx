import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Square } from "lucide-react";
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { client, ok } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Button, Callout, Card, Empty, Field, Input, PageHeader, Problem, QueryState, Select, Table, Td, Th, buttonClass } from "../components/ui";
import { ago, duration, usd, when } from "../lib/format";
import { describe, runStatus } from "../lib/status";
import { RunCounts } from "./Dashboard";

type Mode = "manual" | "discovery" | "mixed";
const MODES: [Mode, string, string][] = [
  ["manual", "Only my targets", "Moves the companies you added as far as each can go."],
  ["discovery", "Discover new companies", "Searches the web for companies matching the campaign's ideal customer, then moves them on."],
  ["mixed", "My targets and discovery", "Both of the above in one run."],
];
const WORKER_SILENT_MS = 45_000;

export function RunsPage() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<Mode>("manual");
  const [limit, setLimit] = useState(50);
  const [discover, setDiscover] = useState(10);
  const [campaign, setCampaign] = useState("");

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
    mutationFn: () => ok(client.POST("/api/runs", { body: { mode, limit, discover, ...(mode !== "manual" && campaign ? { campaign } : {}) } })),
    onSuccess: refresh,
  });
  const cancel = useMutation({ mutationFn: (id: string) => ok(client.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: id } } })), onSuccess: refresh });

  const queuedTooLong = runs.data?.some((r) => r.status === "queued" && Date.now() - new Date(r.created_at).getTime() > WORKER_SILENT_MS);
  const busy = runs.data?.some((r) => r.status === "queued" || r.status === "running");

  return (
    <>
      <PageHeader title="Runs" subtitle="A run moves every company that is due as far as it can go, step by step, and records what it spent." />

      <Card tour="start-run" title="Start a run" className="mb-5">
        <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto] md:items-end">
          <Field label="What to run" hint={MODES.find(([m]) => m === mode)?.[2]}>
            <Select value={mode} onChange={(e) => setMode(e.target.value as Mode)}>
              {MODES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Leads per stage" hint="At most this many per step.">
            <Input type="number" min={1} max={500} value={limit} onChange={(e) => setLimit(Number(e.target.value))} className="w-28" />
          </Field>
          {mode !== "manual" ? (
            <>
              <Field label="Companies to discover">
                <Input type="number" min={1} max={50} value={discover} onChange={(e) => setDiscover(Number(e.target.value))} className="w-28" />
              </Field>
              <Field label="Campaign to search for">
                <Select value={campaign} onChange={(e) => setCampaign(e.target.value)} className="w-48">
                  <option value="">Default</option>
                  {(campaigns.data ?? []).map((c) => (
                    <option key={c.id} value={c.name}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </>
          ) : (
            <div className="hidden md:col-span-2 md:block" />
          )}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3">
          <Button busy={start.isPending} onClick={() => start.mutate()}>
            <Play className="size-3.5 fill-current" aria-hidden /> Start run
          </Button>
          <span className="text-xs text-muted">
            Runs are carried out by the worker process. Budget per prospect: {ceiling == null ? "no limit" : usd(ceiling, 2)}; a lead that reaches it makes no more paid calls.
          </span>
        </div>
        {busy && !queuedTooLong && <p className="mt-2 text-xs text-muted">A run is already queued or running; a new one waits for it.</p>}
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
              <Empty title="No runs yet">Start a run above once you have added targets.</Empty>
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
                      <tr key={run.id} className="align-top hover:bg-surface-low">
                        <Td className="whitespace-nowrap">
                          <Link to="/runs/$runId" params={{ runId: run.id }} className="text-[13px] font-semibold text-primary hover:underline">
                            {ago(run.started_at ?? run.created_at)}
                          </Link>
                          <div className="text-[11px] text-muted" title={when(run.created_at)}>
                            {MODES.find(([m]) => m === params.mode)?.[1] ?? run.kind}
                          </div>
                        </Td>
                        <Td>
                          <StatusBadge status={describe(runStatus, run.status)} />
                        </Td>
                        <Td>
                          <RunCounts counts={run.counts} />
                        </Td>
                        <Td className="hidden whitespace-nowrap text-xs text-muted md:table-cell">{run.started_at ? duration(run.started_at, run.finished_at) : "not started"}</Td>
                        <Td className="text-right font-mono text-xs">{usd(run.cost_micro_usd)}</Td>
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
