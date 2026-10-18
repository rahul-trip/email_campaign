import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { useState, type KeyboardEvent } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Badge, Card, Empty, Problem, Table, Td, Th, statusTone, usd, when, words } from "../components/ui";

type Stage = Schemas["StageOut"];
type State = Stage["state"];

const LOOK: Record<State, { dot: string; ring: string; label: string; tone: "gray" | "green" | "amber" | "red" | "blue" }> = {
  done: { dot: "bg-green-600 text-white", ring: "border-green-600", label: "Done", tone: "green" },
  current: { dot: "bg-brand text-white", ring: "border-brand", label: "Next up", tone: "blue" },
  waiting: { dot: "bg-amber-500 text-white", ring: "border-amber-500", label: "Your turn", tone: "amber" },
  held: { dot: "bg-amber-500 text-white", ring: "border-amber-500", label: "Held", tone: "amber" },
  failed: { dot: "bg-red-600 text-white", ring: "border-red-600", label: "Failed", tone: "red" },
  stopped: { dot: "bg-red-600 text-white", ring: "border-red-600", label: "Stopped", tone: "red" },
  pending: { dot: "bg-gray-200 text-gray-500", ring: "border-line", label: "Not reached", tone: "gray" },
};
const MARK: Record<State, string> = { done: "✓", current: "•", waiting: "!", held: "!", failed: "×", stopped: "×", pending: "" };

/** The stage worth looking at first: the one that is blocked or waiting, else the last one done. */
function defaultStage(stages: Stage[]): string {
  const open = stages.find((s) => s.state !== "done" && s.state !== "pending");
  return (open ?? [...stages].reverse().find((s) => s.state === "done") ?? stages[0]).key;
}

export function LeadJourneyPage() {
  const { companyId } = useParams({ from: "/leads/$companyId/journey" });
  const path = { params: { path: { company_id: companyId } } };
  const journey = useQuery({ queryKey: ["journey", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/journey", path)) });
  const lead = useQuery({ queryKey: ["lead", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}", path)) });
  const [picked, setPicked] = useState<string | null>(null);

  if (journey.isPending || lead.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (journey.isError || lead.isError) return <Problem error={journey.error ?? lead.error} />;

  const { company, contacts } = lead.data;
  const trail = journey.data;
  const selected = trail.stages.find((s) => s.key === (picked ?? defaultStage(trail.stages))) ?? trail.stages[0];
  const finished = trail.stages.filter((s) => s.state === "done").length;
  const blocked = trail.stages.some((s) => ["held", "failed", "stopped"].includes(s.state));

  return (
    <div className="space-y-4">
      <div className="text-sm">
        <Link to="/leads" className="text-muted hover:underline">
          ← Leads
        </Link>
      </div>

      <Card tour="journey-header">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">{company.name ?? company.domain}</h1>
            <p className="mt-0.5 text-sm text-muted">
              {company.domain}
              {company.country_code ? ` · ${company.country_code}` : ""}
              {company.fit_score != null ? ` · fit ${company.fit_score}` : ""}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(company.status)}>{trail.headline}</Badge>
            <Link to="/leads/$companyId" params={{ companyId }} className="rounded-md border border-line bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50">
              Open lead to act on it
            </Link>
          </div>
        </div>

        <div
          className={`mt-4 rounded-md border-l-4 p-3 text-sm ${blocked ? "border-amber-500 bg-amber-50" : "border-brand bg-blue-50"}`}
          role="status"
        >
          <p className="font-medium">What happens next</p>
          <p className="mt-0.5">{trail.next_step}</p>
        </div>

        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          <Number label="Stages done" value={`${finished} of ${trail.stages.length}`} />
          <Number label="Spent on this lead" value={usd(trail.total_cost_micro_usd)} />
          <Number label="People found" value={String(contacts.length)} />
          <Number label="Emails written" value={String(lead.data.messages.length)} />
        </dl>
      </Card>

      <Stepper stages={trail.stages} selected={selected.key} onPick={setPicked} />

      <div className="grid gap-4 lg:grid-cols-[1fr_20rem]">
        <StagePanel stage={selected} />
        <div className="space-y-4">
          <Card tour="journey-origin" title="How this lead arrived">
            <p className="text-sm font-medium">{trail.origin.how}</p>
            <p className="mt-0.5 text-xs text-muted">
              {when(trail.origin.at)}
              {trail.origin.by ? ` · by ${trail.origin.by}` : ""}
            </p>
            <Facts facts={trail.origin.facts} />
          </Card>
        </div>
      </div>
    </div>
  );
}

function Number({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-gray-50 p-2.5">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-base font-semibold">{value}</dd>
    </div>
  );
}

function Stepper({ stages, selected, onPick }: { stages: Stage[]; selected: string; onPick: (key: string) => void }) {
  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = stages[(index + step + stages.length) % stages.length];
    onPick(next.key);
    document.getElementById(`tab-${next.key}`)?.focus();
  };
  return (
    <nav aria-label="Stages" data-tour="journey-stages" className="overflow-x-auto rounded-lg border border-line bg-panel p-3">
      <ol role="tablist" aria-label="Lead stages" className="flex min-w-[44rem] items-start">
        {stages.map((stage, index) => {
          const look = LOOK[stage.state];
          const active = stage.key === selected;
          return (
            <li key={stage.key} role="presentation" className="relative flex flex-1 flex-col items-center">
              {index > 0 && (
                <span aria-hidden className={`absolute left-[-50%] top-4 h-0.5 w-full ${stage.state === "pending" ? "bg-line" : "bg-green-600"}`} />
              )}
              <button
                id={`tab-${stage.key}`}
                role="tab"
                aria-selected={active}
                aria-controls="stage-panel"
                tabIndex={active ? 0 : -1}
                onClick={() => onPick(stage.key)}
                onKeyDown={(e) => move(e, index)}
                className="relative z-10 flex flex-col items-center gap-1.5 rounded-md px-1 py-1 outline-none focus-visible:ring-2 focus-visible:ring-brand"
              >
                <span className={`flex h-8 w-8 items-center justify-center rounded-full border-2 bg-white text-sm font-bold ${look.ring} ${active ? "ring-4 ring-blue-100" : ""}`}>
                  <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs ${look.dot}`}>{MARK[stage.state] || index + 1}</span>
                </span>
                <span className={`text-xs ${active ? "font-semibold" : "text-muted"}`}>{stage.label}</span>
                <span className="sr-only">{look.label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

function StagePanel({ stage }: { stage: Stage }) {
  const look = LOOK[stage.state];
  return (
    <div id="stage-panel" role="tabpanel" aria-labelledby={`tab-${stage.key}`}>
      <Card
        tour="journey-stage"
        title={
          <span className="flex items-center gap-2">
            {stage.label} <Badge tone={look.tone}>{look.label}</Badge>
          </span>
        }
        actions={stage.reached_at ? <span className="text-xs text-muted">reached {when(stage.reached_at)}</span> : undefined}
      >
        <p className="text-sm">{stage.summary}</p>

        {stage.incidents.length > 0 && (
          <div className="mt-3 space-y-1">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Holds, failures and overrides</h3>
            {stage.incidents.map((incident, index) => (
              <p key={index} className="rounded bg-amber-50 p-2 text-sm">
                <span className="text-xs text-muted">{when(incident.at)}</span> {incident.text}
              </p>
            ))}
          </div>
        )}

        {stage.facts.length > 0 && (
          <div className="mt-3">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Details</h3>
            <Facts facts={stage.facts} />
          </div>
        )}
        {stage.facts.length === 0 && stage.state === "pending" && <Empty>This stage has not started.</Empty>}

        {stage.calls.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">
              Vendor calls · {usd(stage.cost_micro_usd)}
            </h3>
            <Table>
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Provider</Th>
                  <Th>Call</Th>
                  <Th>Result</Th>
                  <Th>Cost</Th>
                </tr>
              </thead>
              <tbody>
                {stage.calls.map((call, index) => (
                  <tr key={index}>
                    <Td>{when(call.at)}</Td>
                    <Td>{call.provider}</Td>
                    <Td>{call.operation}</Td>
                    <Td>
                      <Badge tone={call.outcome === "cache_hit" ? "blue" : call.outcome === "error" || call.outcome === "blocked_by_cap" ? "red" : "gray"}>{words(call.outcome)}</Badge>
                    </Td>
                    <Td>{usd(call.cost_micro_usd)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </Card>
    </div>
  );
}

function Facts({ facts }: { facts: Schemas["FactOut"][] }) {
  return (
    <dl className="mt-2 divide-y divide-line text-sm">
      {facts.map((fact, index) => (
        <div key={index} className="grid grid-cols-[8rem_1fr] gap-2 py-1.5">
          <dt className="text-muted">{fact.label}</dt>
          <dd className="break-words">{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}
