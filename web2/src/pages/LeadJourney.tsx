import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { AlertCircle, Check, Clock, Coins, FileText, Info, Layers, Users, X } from "lucide-react";
import { useState, type KeyboardEvent } from "react";
import { client, ok, type Schemas } from "../api/client";
import { JOURNEY_POLICY_STAGE, PolicySkip } from "../components/PolicySkip";
import { StatusBadge } from "../components/StatusBadge";
import { Callout, Card, Facts, Label, PageHeader, Problem, Skeleton, Table, Td, Th, buttonClass } from "../components/ui";
import { cx } from "../lib/cx";
import { usd, when, words } from "../lib/format";
import { callOutcome, describe } from "../lib/status";

type Stage = Schemas["StageOut"];
type State = Stage["state"];

const LOOK: Record<State, { dot: string; label: string; icon: typeof Check }> = {
  done: { dot: "bg-good text-white", label: "Done", icon: Check },
  current: { dot: "bg-working text-white", label: "Next up", icon: Clock },
  waiting: { dot: "bg-attention text-white", label: "Your turn", icon: Clock },
  held: { dot: "bg-attention text-white", label: "Held", icon: AlertCircle },
  failed: { dot: "bg-error text-white", label: "Failed", icon: X },
  stopped: { dot: "bg-error text-white", label: "Stopped", icon: X },
  pending: { dot: "bg-surface-container text-muted", label: "Not reached", icon: Clock },
};

/** The stage worth looking at first: the one blocked or waiting, else the last one done. */
function firstStage(stages: Stage[]): string {
  const open = stages.find((s) => s.state !== "done" && s.state !== "pending");
  return (open ?? [...stages].reverse().find((s) => s.state === "done") ?? stages[0]).key;
}

export function LeadJourneyPage() {
  const { companyId } = useParams({ from: "/leads/$companyId/journey" });
  const path = { params: { path: { company_id: companyId } } };
  const journey = useQuery({ queryKey: ["journey", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/journey", path)) });
  const lead = useQuery({ queryKey: ["lead", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}", path)) });
  const [picked, setPicked] = useState<string | null>(null);

  if (journey.isPending || lead.isPending) return <Skeleton rows={8} />;
  if (journey.isError || lead.isError) return <Problem error={journey.error ?? lead.error} />;

  const { company, contacts, messages } = lead.data;
  const trail = journey.data;
  const selected = trail.stages.find((s) => s.key === (picked ?? firstStage(trail.stages))) ?? trail.stages[0];
  const finished = trail.stages.filter((s) => s.state === "done").length;
  const blocked = trail.stages.some((s) => ["held", "failed", "stopped", "waiting"].includes(s.state));

  return (
    <>
      <PageHeader
        crumbs={
          <>
            <Link to="/leads" className="hover:text-ink hover:underline">
              Leads
            </Link>{" "}
            /{" "}
            <Link to="/leads/$companyId" params={{ companyId }} className="hover:text-ink hover:underline">
              {company.name ?? company.domain}
            </Link>{" "}
            / <span className="text-ink">Journey</span>
          </>
        }
        title={`Journey: ${company.name ?? company.domain}`}
        subtitle={`${company.domain} · country ${company.country_code ?? "unknown"} · fit ${company.fit_score ?? "?"}/100`}
        actions={
          <Link to="/leads/$companyId" params={{ companyId }} className={buttonClass("primary")}>
            Open the lead to act on it
          </Link>
        }
      />

      <div data-tour="journey-header" className="mb-5">
        <Callout tone={blocked ? "attention" : "info"} title={trail.headline} className="text-[13px]">
          <span className="font-semibold">What happens next: </span>
          {trail.next_step}
        </Callout>
      </div>

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile icon={<Layers className="size-4" />} label="Stages done" value={`${finished} of ${trail.stages.length}`} />
        <Tile icon={<Coins className="size-4" />} label="Spent on this lead" value={usd(trail.total_cost_micro_usd)} />
        <Tile icon={<Users className="size-4" />} label="People found" value={String(contacts.length)} />
        <Tile icon={<FileText className="size-4" />} label="Emails written" value={String(messages.length)} />
      </div>

      <Stepper stages={trail.stages} selected={selected.key} onPick={setPicked} />

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
        <StagePanel stage={selected} lead={lead.data} />
        <Card tour="journey-origin" title="How this lead arrived">
          <p className="text-[13px] font-medium">{trail.origin.how}</p>
          <p className="mt-0.5 text-xs text-muted">
            {when(trail.origin.at)}
            {trail.origin.by && ` · by ${trail.origin.by}`}
          </p>
          {trail.origin.facts.length > 0 && (
            <div className="mt-3">
              <Facts facts={trail.origin.facts} />
            </div>
          )}
        </Card>
      </div>
    </>
  );
}

function Tile({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-line bg-surface p-3.5">
      <span className="flex size-8 items-center justify-center rounded-lg bg-surface-container text-muted" aria-hidden>
        {icon}
      </span>
      <div>
        <div className="font-mono text-lg font-semibold">{value}</div>
        <div className="text-[11px] text-muted">{label}</div>
      </div>
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
    document.getElementById(`stage-${next.key}`)?.focus();
  };
  return (
    <Card tour="journey-stages" className="overflow-x-auto">
      <ol role="tablist" aria-label="Stages of this lead" className="flex min-w-[720px] items-start">
        {stages.map((stage, index) => {
          const look = LOOK[stage.state];
          const Icon = look.icon;
          const active = stage.key === selected;
          return (
            <li key={stage.key} role="presentation" className="relative flex flex-1 flex-col items-center">
              {index > 0 && <span aria-hidden className={cx("absolute right-1/2 top-[18px] h-0.5 w-full", stage.state === "pending" ? "bg-line" : "bg-good")} />}
              <button
                id={`stage-${stage.key}`}
                type="button"
                role="tab"
                aria-selected={active}
                aria-controls="stage-panel"
                tabIndex={active ? 0 : -1}
                onClick={() => onPick(stage.key)}
                onKeyDown={(e) => move(e, index)}
                className={cx("relative z-10 flex flex-col items-center gap-1.5 rounded-lg px-2 py-1 outline-none focus-visible:ring-2 focus-visible:ring-primary-container/40", active && "bg-surface-low")}
              >
                <span className={cx("flex size-8 items-center justify-center rounded-full ring-4 ring-surface", look.dot, active && "outline outline-2 outline-offset-2 outline-primary-container")}>
                  <Icon className="size-4" aria-hidden />
                </span>
                <span className={cx("text-center text-xs", active ? "font-semibold" : "text-muted")}>{stage.label}</span>
                <span className="text-[10px] text-muted">{look.label}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

function StagePanel({ stage, lead }: { stage: Stage; lead: Schemas["LeadOut"] }) {
  const policyStage = JOURNEY_POLICY_STAGE[stage.key];
  const company = lead.company;
  // Offer the skip where the country rule stopped this lead, or where it is already skipped.
  const stoppedHere =
    (lead.held_at && lead.held_at === policyStage) ||
    (stage.key === "qualification" && company.status === "disqualified" && (company.policy_decision as { outcome?: string } | null)?.outcome === "block");
  const skippedFromHere = company.policy_skip_from === policyStage;
  const look = LOOK[stage.state];
  return (
    <div id="stage-panel" role="tabpanel" aria-labelledby={`stage-${stage.key}`} data-tour="journey-stage">
      <Card
        title={
          <span className="flex items-center gap-2">
            {stage.label}
            <span className={cx("rounded-full px-2 py-0.5 text-[11px] font-medium", stage.state === "done" ? "bg-good-container text-on-good-container" : stage.state === "pending" ? "bg-surface-container text-muted" : ["failed", "stopped"].includes(stage.state) ? "bg-error-container text-on-error-container" : "bg-attention-container text-on-attention-container")}>
              {look.label}
            </span>
          </span>
        }
        actions={<span className="font-mono text-xs text-muted">{usd(stage.cost_micro_usd)}</span>}
      >
        <p className="text-[13px] leading-relaxed">{stage.summary || "Nothing recorded for this stage yet."}</p>
        {stage.reached_at && <p className="mt-1 text-[11px] text-muted">Reached {when(stage.reached_at)}</p>}

        {stage.incidents.length > 0 && (
          <div className="mt-4 space-y-2">
            <Label>Holds, failures and overrides</Label>
            {stage.incidents.map((incident, i) => (
              <Callout key={i} tone="attention">
                {incident.text}
                <div className="mt-0.5 text-[11px] opacity-80">{when(incident.at)}</div>
              </Callout>
            ))}
          </div>
        )}

        {policyStage && (stoppedHere || skippedFromHere) && (
          <div className="mt-4" data-tour="journey-policy-skip">
            <Label className="mb-2">Country rule</Label>
            <PolicySkip company={company} heldAt={lead.held_at} preset={policyStage} />
          </div>
        )}

        {stage.facts.length > 0 && (
          <div className="mt-4">
            <Label className="mb-2 flex items-center gap-1.5">
              <Info className="size-3.5" aria-hidden /> Details
            </Label>
            <Facts facts={stage.facts} />
          </div>
        )}

        {stage.calls.length > 0 && (
          <div className="mt-4">
            <Label className="mb-2 flex items-center gap-1.5">
              <Coins className="size-3.5" aria-hidden /> Vendor calls · {usd(stage.cost_micro_usd)}
            </Label>
            <Table className="rounded-lg border border-line">
              <thead>
                <tr>
                  <Th>When</Th>
                  <Th>Vendor</Th>
                  <Th>Call</Th>
                  <Th>Result</Th>
                  <Th className="text-right">Cost</Th>
                </tr>
              </thead>
              <tbody>
                {stage.calls.map((call, i) => (
                  <tr key={i}>
                    <Td className="whitespace-nowrap text-xs text-muted">{when(call.at)}</Td>
                    <Td className="font-medium">{call.provider}</Td>
                    <Td className="text-xs">{words(call.operation)}</Td>
                    <Td>
                      <StatusBadge status={describe(callOutcome, call.outcome)} />
                    </Td>
                    <Td className="text-right font-mono text-xs">{usd(call.cost_micro_usd)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
        {stage.state === "pending" && stage.facts.length === 0 && <p className="mt-3 text-xs text-muted">This stage has not started.</p>}
      </Card>
    </div>
  );
}
