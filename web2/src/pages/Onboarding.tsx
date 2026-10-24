/** A guided first setup: the same screens as Settings, one step at a time, in the order a new
 * workspace needs them. Each step's tick comes from the server's setup list, so finishing a
 * step anywhere (here or in Settings) ticks it here. */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Check } from "lucide-react";
import { useState } from "react";
import { client, ok } from "../api/client";
import { useCurrent } from "../app/session";
import { Button, Callout, Card, PageHeader, QueryState, buttonClass } from "../components/ui";
import { cx } from "../lib/cx";
import { useSetup } from "../lib/setup";
import { CampaignForm } from "./Campaigns";
import { Mailboxes } from "./Mailboxes";
import { SenderProfile } from "./Settings";

type StepId = "company" | "mailbox" | "campaign" | "leads";

const STEPS: { id: StepId; title: string; why: string; items: string[] }[] = [
  { id: "company", title: "Your company", why: "Who you are in every email, and what the writer may truthfully say. Nothing is written until you confirm it.", items: ["profile", "legal", "signature"] },
  { id: "mailbox", title: "A mailbox", why: "Approved emails are saved as drafts here for you to send. You can skip this and connect one later.", items: ["mailbox", "dns"] },
  { id: "campaign", title: "Who to reach", why: "The job titles you want and a description of your ideal customer. Research, ranking and the fit score read this.", items: ["campaign"] },
  { id: "leads", title: "Your first leads", why: "Add a few companies, then start a run.", items: ["leads"] },
];

export function OnboardingPage() {
  const { workspace } = useCurrent();
  const setup = useSetup();
  const [chosen, setChosen] = useState<StepId | null>(null);
  const status = new Map((setup.data?.items ?? []).map((i) => [i.key, i.status]));
  const doneStep = (id: StepId) => STEPS.find((s) => s.id === id)!.items.every((key) => status.get(key) === "ok" || (id !== "company" && id !== "campaign" && status.get(key) === "warning"));
  const firstOpen = STEPS.find((s) => !doneStep(s.id))?.id ?? "leads";
  const current = chosen ?? firstOpen;
  const index = STEPS.findIndex((s) => s.id === current);
  const step = STEPS[index]!;

  if (workspace.role !== "admin") return <Callout>Setting up the workspace is for admins. Ask one of yours.</Callout>;
  return (
    <>
      <PageHeader title="Set up your workspace" subtitle="Four short steps. You can leave and come back; your progress is saved as you go." />
      {setup.data?.done && (
        <Callout tone="good" className="mb-5" title="You are ready to start">
          Everything the engine needs is in place.{" "}
          <Link to="/targets" className="font-semibold underline">Add your first leads</Link> or <Link to="/" className="font-semibold underline">go to the dashboard</Link>.
        </Callout>
      )}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[240px_minmax(0,1fr)]">
        <nav aria-label="Setup steps" data-tour="onboarding-steps">
          <ol className="space-y-1">
            {STEPS.map((s, n) => {
              const complete = doneStep(s.id);
              return (
                <li key={s.id}>
                  <button type="button" aria-current={s.id === current ? "step" : undefined} onClick={() => setChosen(s.id)} className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-[13px] hover:bg-surface-low", s.id === current && "bg-primary-fixed font-semibold text-primary")}>
                    <span className={cx("flex size-5 shrink-0 items-center justify-center rounded-full border text-[11px]", complete ? "border-good bg-good text-white" : "border-outline")}>
                      {complete ? <Check className="size-3" aria-label="Done" /> : n + 1}
                    </span>
                    {s.title}
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>
        <div className="min-w-0 space-y-4">
          <Card title={`${index + 1}. ${step.title}`} subtitle={step.why}>
            {step.id === "company" && <SenderProfile />}
            {step.id === "mailbox" && <Mailboxes />}
            {step.id === "campaign" && <FirstCampaign />}
            {step.id === "leads" && (
              <div className="flex flex-wrap items-center gap-3 text-[13px]">
                <Link to="/targets" className={buttonClass("primary")}>Add leads <ArrowRight className="size-4" aria-hidden /></Link>
                <span className="text-muted">Type a website, paste a list or upload a file. Then press Start run.</span>
              </div>
            )}
          </Card>
          <div className="flex items-center justify-between">
            <Button variant="secondary" disabled={index === 0} onClick={() => setChosen(STEPS[index - 1]!.id)}>Back</Button>
            {index < STEPS.length - 1 ? (
              <Button onClick={() => setChosen(STEPS[index + 1]!.id)}>{doneStep(step.id) ? "Next" : "Skip for now"}</Button>
            ) : (
              <Link to="/" className={buttonClass("secondary")}>Finish</Link>
            )}
          </div>
        </div>
      </div>
    </>
  );
}

/** The workspace starts with one empty campaign; this fills it in. */
function FirstCampaign() {
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  return <QueryState query={campaigns}>{(all) => <CampaignForm campaign={all[0]} onSaved={() => void campaigns.refetch()} />}</QueryState>;
}

