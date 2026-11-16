/** A guided first setup, one decision at a time. The company and the campaign are drafted from the
 * person's own website and profile for them to check; each step's tick comes from the server's
 * setup list, so finishing a step anywhere (here or in Settings) ticks it here. */
import { Link } from "@tanstack/react-router";
import { Check } from "lucide-react";
import { useState } from "react";
import { useCurrent } from "../app/session";
import { Button, Callout, Card, PageHeader, buttonClass } from "../components/ui";
import { cx } from "../lib/cx";
import { useSetup } from "../lib/setup";
import { useTour } from "../tour/Tour";
import { Mailboxes } from "./Mailboxes";
import { Audience } from "./onboarding/Audience";
import { Company } from "./onboarding/Company";
import { FirstLeads } from "./onboarding/FirstLeads";
import { Sender } from "./onboarding/Sender";

type StepId = "company" | "sender" | "campaign" | "leads" | "mailbox";

const STEPS: { id: StepId; title: string; why: string; items: string[]; required: boolean }[] = [
  { id: "company", title: "What you sell", items: ["profile"], required: true, why: "We read your website and draft this for you. Keep only what is true: it ends up in emails under your name." },
  { id: "sender", title: "Who signs", items: ["legal", "signature"], required: true, why: "Your name ends every email. Your legal name and address go in the footer the law requires." },
  { id: "campaign", title: "Who to reach", items: ["campaign"], required: true, why: "The job titles you want and what your ideal customer looks like. Everything else is found from this." },
  { id: "leads", title: "Your first leads", items: ["leads"], required: false, why: "Let the engine find companies that fit, or bring your own list." },
  { id: "mailbox", title: "A mailbox", items: ["mailbox", "dns"], required: false, why: "Approved emails are saved here as drafts for you to send. You can connect it later." },
];

export function OnboardingPage() {
  const { workspace } = useCurrent();
  const setup = useSetup();
  const { start } = useTour();
  const [chosen, setChosen] = useState<StepId | null>(null);
  const status = new Map((setup.data?.items ?? []).map((i) => [i.key, i.status]));
  const doneStep = (id: StepId) => {
    const step = STEPS.find((s) => s.id === id)!;
    return step.items.every((key) => status.get(key) === "ok" || (!step.required && status.get(key) === "warning"));
  };
  const firstOpen = STEPS.find((s) => !doneStep(s.id))?.id ?? "leads";
  const current = chosen ?? firstOpen;
  const index = STEPS.findIndex((s) => s.id === current);
  const step = STEPS[index]!;
  const last = index === STEPS.length - 1;
  const next = () => setChosen(STEPS[Math.min(index + 1, STEPS.length - 1)]!.id);

  if (workspace.role !== "admin") return <Callout>Setting up the workspace is for admins. Ask one of yours.</Callout>;
  return (
    <>
      <PageHeader title="Set up your workspace" subtitle="Five short steps. Your progress is saved as you go." />
      {setup.data?.done && (
        <Callout tone="good" className="mb-5" title="You are ready to start">
          Everything the engine needs is in place.{" "}
          <Link to="/targets" className="font-semibold underline">Add leads</Link> or <Link to="/" className="font-semibold underline">go to the dashboard</Link>.
        </Callout>
      )}
      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[240px_minmax(0,1fr)]">
        <nav aria-label="Setup steps" data-tour="onboarding-steps">
          <ol className="space-y-1">
            {STEPS.map((s, n) => {
              const complete = doneStep(s.id);
              return (
                <li key={s.id}>
                  <button type="button" aria-current={s.id === current ? "step" : undefined} onClick={() => setChosen(s.id)} className={cx("flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left text-body hover:bg-surface-low", s.id === current && "bg-primary-fixed font-semibold text-primary")}>
                    <span className={cx("flex size-5 shrink-0 items-center justify-center rounded-full border text-caption", complete ? "border-good bg-good text-white" : "border-outline")}>
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
          <p className="text-xs font-semibold uppercase tracking-wider text-muted">Step {index + 1} of {STEPS.length}</p>
          <Card title={step.title} subtitle={step.why}>
            {step.id === "company" && <Company onNext={next} />}
            {step.id === "sender" && <Sender onNext={next} />}
            {step.id === "campaign" && <Audience onNext={next} />}
            {step.id === "leads" && <FirstLeads onNext={next} />}
            {step.id === "mailbox" && (
              <div className="space-y-4">
                <Mailboxes />
                <div className="flex flex-wrap items-center gap-3 border-t border-line pt-4">
                  <Link to="/" className={buttonClass("primary")}>Finish</Link>
                  <Button variant="secondary" onClick={start}>Take the tour</Button>
                </div>
              </div>
            )}
          </Card>
          <div className="flex items-center justify-between">
            <Button variant="secondary" disabled={index === 0} onClick={() => setChosen(STEPS[index - 1]!.id)}>Back</Button>
            {!last && (
              <Button variant="secondary" disabled={step.id === "campaign" && !doneStep(step.id)} onClick={next}>
                {doneStep(step.id) ? "Next" : "Skip for now"}
              </Button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
