/** Step 4: start the first discovery run, or bring a list. The person watches it work. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Search } from "lucide-react";
import { useState } from "react";
import { client, ok } from "../../api/client";
import { Button, Callout, Card, Problem, buttonClass } from "../../ui/compat";
import { discoveryLine, totalsOf } from "../../lib/runs";
import { useUsage } from "../../lib/usage";

export function FirstLeads({ onNext }: { onNext: () => void }) {
  const queryClient = useQueryClient();
  const usage = useUsage();
  const [startedId, setStartedId] = useState<string | null>(null);
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => ok(client.GET("/api/runs")),
    refetchInterval: (query) => (query.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2000 : 10000),
  });
  const auto = useQuery({ queryKey: ["auto-discovery"], queryFn: () => ok(client.GET("/api/runs/auto-discovery")) });
  const working = runs.data?.find((r) => r.status === "queued" || r.status === "running");
  const run = runs.data?.find((r) => r.id === startedId) ?? working;
  const start = useMutation({
    mutationFn: () => ok(client.POST("/api/runs", { body: { mode: "discovery", discover: 10 } })),
    onSuccess: (made) => {
      setStartedId(made.id);
      for (const key of ["runs", "setup", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  const step = usage.data?.steps.find((s) => s.step === "discovery");
  const noCredit = (step && step.limit !== null && (step.remaining ?? 1) <= 0) || usage.data?.engine === false;
  const totals = run ? totalsOf(run.counts) : null;
  const line = totals ? discoveryLine(totals) : null;
  const finished = run && run.status !== "queued" && run.status !== "running";
  const waitingOn = auto.data && (auto.data.reason === null || auto.data.reason === "not_yet");

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Find companies for me" subtitle="The engine searches the web for companies that match who you described, and adds the best as leads.">
          <Button busy={start.isPending} disabled={Boolean(noCredit) || Boolean(working)} onClick={() => start.mutate()}>
            <Search className="size-4" aria-hidden /> Find 10 companies now
          </Button>
          {noCredit && <p className="mt-2 text-small text-muted">Your plan has no search credit left. Bring your own list instead.</p>}
          {working && !startedId && <p className="mt-2 text-small text-muted">A run is already working. Watch it below.</p>}
          <Problem error={start.error} className="mt-2" />
        </Card>
        <Card title="I have my own list" subtitle="Type a website, paste a list or upload a file.">
          <Link to="/targets" className={buttonClass("secondary")}>
            Add leads <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Card>
      </div>
      {run && (
        <Callout tone={finished ? "good" : "info"} title={run.status === "queued" ? "Waiting to start" : run.status === "running" ? "Searching now" : "The search has finished"}>
          {line ?? (finished ? "It finished without adding companies." : "This takes a few minutes. You can connect a mailbox meanwhile.")}{" "}
          <Link to="/runs/$runId" params={{ runId: run.id }} className="font-semibold underline">
            Watch this run
          </Link>
          {finished && totals && totals.newLeads > 0 && (
            <>
              {" "}
              ·{" "}
              <Link to="/leads" className="font-semibold underline">
                See the leads
              </Link>
            </>
          )}
        </Callout>
      )}
      {waitingOn && <p className="text-small text-muted">After this, the engine looks for more about {auto.data?.per_day} times a day. Change it under Settings → Limits.</p>}
      <Button onClick={onNext}>Next: connect a mailbox</Button>
    </div>
  );
}
