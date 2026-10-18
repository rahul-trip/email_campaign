import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../api/client";
import { Badge, Button, Card, Empty, Field, Input, Problem, Select, Table, Td, Th, statusTone, usd, when } from "../components/ui";

export function RunsPage() {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<"manual" | "discovery" | "mixed">("manual");
  const [limit, setLimit] = useState(50);
  const [discover, setDiscover] = useState(10);
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => ok(client.GET("/api/runs")),
    // Poll while anything is queued or running, so progress and spend update live.
    refetchInterval: (query) => (query.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2000 : false),
  });
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const budget = Number(settings.data?.budget_per_prospect_micro_usd ?? 0);

  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["runs"] });
  const start = useMutation({ mutationFn: () => ok(client.POST("/api/runs", { body: { mode, limit, discover } })), onSuccess: refresh });
  const cancel = useMutation({
    mutationFn: (id: string) => ok(client.POST("/api/runs/{run_id}/cancel", { params: { path: { run_id: id } } })),
    onSuccess: refresh,
  });

  return (
    <div className="space-y-4">
      <Card title="Start a run">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Mode" hint="Discovery also searches for new companies">
            <Select value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
              <option value="manual">Only my targets</option>
              <option value="discovery">Discover new companies</option>
              <option value="mixed">My targets and discovery</option>
            </Select>
          </Field>
          <Field label="Leads per stage">
            <Input type="number" min={1} max={500} value={limit} onChange={(e) => setLimit(Number(e.target.value))} />
          </Field>
          {mode !== "manual" && (
            <Field label="Companies to discover">
              <Input type="number" min={1} max={50} value={discover} onChange={(e) => setDiscover(Number(e.target.value))} />
            </Field>
          )}
          <Button onClick={() => start.mutate()} disabled={start.isPending}>
            Start run
          </Button>
        </div>
        <p className="mt-2 text-xs text-muted">
          Runs are queued and executed by the worker process (<code>outbound worker</code>). Per-prospect budget: {usd(budget, 2)}.
        </p>
        <Problem error={start.error ?? cancel.error} />
      </Card>

      <Card title="Recent runs">
        {runs.data?.length === 0 && <Empty>No runs yet.</Empty>}
        <Table>
          <thead>
            <tr>
              <Th>Started</Th>
              <Th>Status</Th>
              <Th>Progress</Th>
              <Th>Spend</Th>
              <Th />
            </tr>
          </thead>
          <tbody>
            {runs.data?.map((run) => (
              <tr key={run.id}>
                <Td>{when(run.started_at ?? run.created_at)}</Td>
                <Td>
                  <Badge tone={statusTone(run.status)}>{run.status}</Badge>
                </Td>
                <Td className="text-muted">
                  {Object.entries(run.counts ?? {})
                    .map(([stage, c]) => (typeof c === "object" && c ? `${stage}: ${Object.entries(c).map(([k, n]) => `${n} ${k}`).join(", ")}` : `${stage}: ${String(c)}`))
                    .join(" · ")}
                </Td>
                <Td>{usd(run.cost_micro_usd)}</Td>
                <Td>
                  {(run.status === "queued" || run.status === "running") && (
                    <Button variant="secondary" onClick={() => cancel.mutate(run.id)}>
                      Cancel
                    </Button>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
    </div>
  );
}
