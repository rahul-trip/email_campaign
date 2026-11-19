/**
 * Setup as a full-screen, three-phase flow: a welcome with a goal choice, five steps with a
 * live progress ring and a "what Outbound will do for you" card per step, and a celebration
 * with what happens next. The step forms are web2's (drafted from the person's own site and
 * profile); each tick comes from the server's setup list, so finishing a step anywhere ticks it.
 * Every claim on these screens is something the product really does.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, ArrowRight, Check, Compass, Inbox, LogOut, Mail, Radar, ShieldCheck, Sparkles, Target, Users, Wand2 } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { client, ok } from "../api/client";
import { useCurrent } from "../app/session";
import { useTour } from "../app/tour";
import { cx } from "../lib/cx";
import { useSetup } from "../lib/setup";
import { Button, buttonClass, Callout, Chip } from "../ui/core";
import { FitRing, Ring } from "../ui/viz";
import { Mailboxes } from "./Mailboxes";
import { Audience } from "./onboarding/Audience";
import { Company } from "./onboarding/Company";
import { FirstLeads } from "./onboarding/FirstLeads";
import { Sender } from "./onboarding/Sender";

type StepId = "company" | "sender" | "campaign" | "leads" | "mailbox";
type Goal = "market" | "list" | "both";

const STEPS: { id: StepId; title: string; short: string; why: string; items: string[]; required: boolean; icon: ReactNode; promise: string[] }[] = [
  {
    id: "company",
    title: "What you sell",
    short: "Your company, drafted from your website",
    icon: <Sparkles className="size-4" />,
    items: ["profile"],
    required: true,
    why: "We read your website and draft this for you. Keep only what is true: it ends up in emails under your name.",
    promise: ["We read your site so you never start from a blank page.", "Only what you confirm is used in your emails."],
  },
  {
    id: "sender",
    title: "Who signs",
    short: "Your name, legal name and address",
    icon: <Mail className="size-4" />,
    items: ["legal", "signature"],
    required: true,
    why: "Your name ends every email. Your legal name and address go in the footer the law requires.",
    promise: ["UK and EU law ask for a real postal address in every cold email. We add it for you, every time.", "The footer for each country is checked again before any draft is saved."],
  },
  {
    id: "campaign",
    title: "Who to reach",
    short: "Job titles and your ideal customer",
    icon: <Target className="size-4" />,
    items: ["campaign"],
    required: true,
    why: "The job titles you want and what your ideal customer looks like. Everything else is found from this.",
    promise: ["Discovery looks for companies like these about four times a day.", "Each company is scored against your must-haves, signals and rule-outs; only fits become leads."],
  },
  {
    id: "leads",
    title: "Your first leads",
    short: "Let it search, or bring a list",
    icon: <Radar className="size-4" />,
    items: ["leads"],
    required: false,
    why: "Let the engine find companies that fit, or bring your own list.",
    promise: ["Every address is checked before it is used; catch-all domains wait until they are proven.", "You pay credits only for leads that pass your brief."],
  },
  {
    id: "mailbox",
    title: "A mailbox",
    short: "Where approved drafts are saved",
    icon: <Inbox className="size-4" />,
    items: ["mailbox", "dns"],
    required: false,
    why: "Approved emails are saved here as drafts for you to send. You can connect it later.",
    promise: ["Nothing is sent by itself: approved emails land in your Drafts and you press send.", "Opt-out replies and hard bounces are spotted in your inbox and handled for you."],
  },
];

const GOALS: { key: Goal; label: string; line: string }[] = [
  { key: "market", label: "Book meetings in a new market", line: "We will lean on discovery: it finds companies that fit your brief while you work." },
  { key: "list", label: "Work through my own list", line: "Bring a list or add companies one by one; we research, verify and write for each." },
  { key: "both", label: "Both", line: "Start with your list, and let discovery top it up with companies that fit." },
];

const WELCOMED = "outbound.onboarding.welcomed";
const read = (key: string) => {
  try {
    return sessionStorage.getItem(key);
  } catch {
    return null;
  }
};
const write = (key: string, value: string) => {
  try {
    sessionStorage.setItem(key, value);
  } catch {
    // storage blocked: the choice lasts while the page is open
  }
};

export function OnboardingPage() {
  const { workspace, me } = useCurrent();
  const setup = useSetup();
  const [phase, setPhase] = useState<"welcome" | "steps" | "done" | null>(null);
  const [goal, setGoal] = useState<Goal>((read("outbound.onboarding.goal") as Goal) || "market");
  const [chosen, setChosen] = useState<StepId | null>(null);
  const status = new Map((setup.data?.items ?? []).map((i) => [i.key, i.status]));
  const doneStep = (id: StepId) => {
    const step = STEPS.find((s) => s.id === id)!;
    return step.items.every((key) => status.get(key) === "ok" || (!step.required && status.get(key) === "warning"));
  };
  const doneCount = STEPS.filter((s) => doneStep(s.id)).length;
  // Optional steps count as done when they only warn, so a new workspace is judged by the required ones.
  const nothingYet = setup.isSuccess && STEPS.filter((s) => s.required).every((s) => !doneStep(s.id));

  // First visit with nothing done: the welcome; otherwise straight to the steps.
  useEffect(() => {
    if (phase !== null || !setup.isSuccess) return;
    setPhase(nothingYet && !read(WELCOMED) ? "welcome" : setup.data.done ? "done" : "steps");
  }, [phase, setup.isSuccess, nothingYet, setup.data?.done]);

  if (workspace.role !== "admin")
    return (
      <Frame>
        <Callout className="mx-auto mt-20 max-w-lg">Setting up the workspace is for admins. Ask one of yours.</Callout>
      </Frame>
    );
  if (phase === null) return <Frame />;

  if (phase === "welcome")
    return (
      <Welcome
        name={me.user.name}
        goal={goal}
        onGoal={(g) => {
          setGoal(g);
          write("outbound.onboarding.goal", g);
        }}
        onStart={() => {
          write(WELCOMED, "1");
          setPhase("steps");
        }}
      />
    );
  if (phase === "done") return <Celebration name={me.user.name} onBack={() => setPhase("steps")} />;

  const firstOpen = STEPS.find((s) => !doneStep(s.id))?.id ?? "leads";
  const current = chosen ?? firstOpen;
  const index = STEPS.findIndex((s) => s.id === current);
  const step = STEPS[index]!;
  const last = index === STEPS.length - 1;
  const next = () => (last ? setPhase("done") : setChosen(STEPS[index + 1]!.id));

  return (
    <Frame progress={doneCount / STEPS.length} stepLabel={`Step ${index + 1} of ${STEPS.length}`}>
      <div className="mx-auto grid max-w-[1200px] gap-6 px-4 py-8 sm:px-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <nav aria-label="Setup steps" data-tour="onboarding-steps" className="card p-3">
            <div className="px-2 pt-1 pb-3">
              <div className="text-label font-semibold tracking-wide text-primary uppercase">Your setup</div>
              <div className="text-heading font-semibold text-ink">Let's get your engine running</div>
            </div>
            <ol className="relative space-y-1">
              {STEPS.map((s, n) => {
                const complete = doneStep(s.id);
                const active = s.id === current;
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      aria-current={active ? "step" : undefined}
                      onClick={() => setChosen(s.id)}
                      className={cx("press flex w-full items-start gap-3 rounded-xl px-2.5 py-2.5 text-left transition-colors", active ? "bg-primary-soft" : "hover:bg-surface-2")}
                    >
                      <span
                        className={cx(
                          "mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full text-small font-bold transition-colors",
                          complete ? "bg-good-dot text-white" : active ? "bg-primary text-primary-ink shadow-2" : "bg-surface-3 text-muted",
                        )}
                      >
                        {complete ? <Check className="size-4 animate-pop" aria-label="Done" /> : n + 1}
                      </span>
                      <span className="min-w-0">
                        <span className={cx("flex items-center gap-2 text-body", active ? "font-semibold text-primary" : "font-medium text-ink")}>
                          {s.title}
                          {!s.required && <span className="text-label font-normal text-faint">optional</span>}
                        </span>
                        <span className="block text-small text-muted">{s.short}</span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ol>
            <div className="mt-2 flex items-center gap-2 border-t border-line px-2 pt-3 text-small text-muted">
              <ShieldCheck className="size-4 text-good-dot" aria-hidden /> Your progress is saved as you go.
            </div>
          </nav>
          <Promise key={step.id} lines={step.promise} />
        </aside>

        <main className="min-w-0">
          <div key={step.id} className="animate-rise">
            <div className="mb-5 flex items-start gap-4">
              <span className="flex size-12 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-violet text-white shadow-2">{step.icon}</span>
              <div>
                <h1 className="text-title font-semibold text-ink">{step.title}</h1>
                <p className="mt-1 max-w-[68ch] text-body text-muted">{step.why}</p>
              </div>
              {doneStep(step.id) && <Chip tone="good" className="ml-auto">Done ✓</Chip>}
            </div>
            <div className="card p-6">
              {step.id === "company" && <Company onNext={next} />}
              {step.id === "sender" && <Sender onNext={next} />}
              {step.id === "campaign" && <Audience onNext={next} />}
              {step.id === "leads" && <FirstLeads onNext={next} />}
              {step.id === "mailbox" && <Mailboxes />}
            </div>
          </div>
          <div className="sticky bottom-0 mt-5 flex items-center justify-between gap-3 rounded-2xl border border-line bg-surface/90 px-4 py-3 backdrop-blur">
            <Button variant="ghost" disabled={index === 0} onClick={() => setChosen(STEPS[index - 1]!.id)}>
              <ArrowLeft className="size-4" aria-hidden /> Back
            </Button>
            <span className="hidden text-small text-muted sm:inline">{last ? "Last step" : `Next: ${STEPS[index + 1]!.title}`}</span>
            <Button disabled={step.required && !doneStep(step.id) && step.id === "campaign"} variant={doneStep(step.id) || last ? "primary" : "secondary"} onClick={next}>
              {last ? "Finish setup" : doneStep(step.id) ? "Continue" : step.required ? "Skip for now" : "Skip — do it later"} <ArrowRight className="size-4" aria-hidden />
            </Button>
          </div>
        </main>
      </div>
    </Frame>
  );
}

/** The full-screen frame: logo, progress ring with the step, and a way out. */
function Frame({ children, progress, stepLabel }: { children?: ReactNode; progress?: number; stepLabel?: string }) {
  return (
    <div className="min-h-screen bg-bg">
      <header className="glass sticky top-0 z-20 flex h-16 items-center gap-4 border-b border-line px-4 sm:px-6">
        <span className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-violet text-white shadow-2">
            <Wand2 className="size-4" aria-hidden />
          </span>
          <span className="text-heading font-bold text-ink">Outbound</span>
        </span>
        {progress !== undefined && (
          <span className="mx-auto flex items-center gap-3 rounded-full border border-line bg-surface px-3 py-1">
            <Ring share={progress} size={28} stroke={4} tone="good" title={`${Math.round(progress * 100)}% set up`} />
            <span className="text-small font-semibold text-ink">{stepLabel}</span>
            <span className="tnum text-small text-muted">{Math.round(progress * 100)}% done</span>
          </span>
        )}
        <Link to="/" className={buttonClass("ghost", "sm", "ml-auto")}>
          <LogOut className="size-4" aria-hidden /> Save and finish later
        </Link>
      </header>
      {children}
    </div>
  );
}

/** Rotates the step's honest promises: what Outbound will do once this is set. */
function Promise({ lines }: { lines: string[] }) {
  const [n, setN] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setN((i) => (i + 1) % lines.length), 6000);
    return () => window.clearInterval(timer);
  }, [lines.length]);
  return (
    <div className="relative overflow-hidden rounded-2xl border border-primary-line bg-primary-soft p-5">
      <div className="aurora opacity-60" aria-hidden />
      <div className="relative">
        <div className="text-label font-semibold tracking-wide text-primary uppercase">What Outbound will do for you</div>
        <p key={n} className="mt-2 min-h-[4.5rem] animate-fade text-body text-ink">
          {lines[n]}
        </p>
        <div className="mt-2 flex gap-1.5" aria-hidden>
          {lines.map((_, i) => (
            <span key={i} className={cx("h-1.5 rounded-full transition-all", i === n ? "w-5 bg-primary" : "w-1.5 bg-primary-line")} />
          ))}
        </div>
      </div>
    </div>
  );
}

const PIPELINE = [
  { icon: <Radar className="size-4" />, label: "Found" },
  { icon: <Sparkles className="size-4" />, label: "Researched" },
  { icon: <Users className="size-4" />, label: "Verified" },
  { icon: <Mail className="size-4" />, label: "Written" },
  { icon: <Inbox className="size-4" />, label: "Approved" },
];

/** A made-up example of what lands in Emails ready, labelled as one: it shows the result before anything is set up. */
function ExampleDraft() {
  return (
    <div className="relative overflow-hidden rounded-3xl border border-line bg-surface-2 p-4 shadow-2 sm:p-6" aria-label="An example of a finished draft">
      <div className="aurora" aria-hidden />
      <div className="relative">
        <div className="flex items-center justify-between gap-3">
          <Chip tone="primary">Example · what you will review</Chip>
          <span className="text-label text-muted">Not real data</span>
        </div>
        <div className="mt-4 rounded-2xl border border-line bg-surface p-4 sm:p-5">
          <Chip tone="good" dot>
            Ready to approve
          </Chip>
          <dl className="mt-4 space-y-1 rounded-xl bg-surface-2 p-3 text-small">
            <div className="flex gap-3">
              <dt className="w-10 text-muted">From</dt>
              <dd className="min-w-0 truncate text-ink">you@your-company.com</dd>
            </div>
            <div className="flex items-center gap-3">
              <dt className="w-10 text-muted">To</dt>
              <dd className="min-w-0 truncate text-ink">a decision-maker, address verified</dd>
            </div>
          </dl>
          <div className="mt-4 text-label text-muted">Subject</div>
          <div className="text-heading font-semibold text-ink">A quick question about how you handle inbound</div>
          <p className="mt-3 border-l-2 border-primary-line pl-3 text-body text-ink-2">
            Short and specific: it opens with something true about their company, taken from the research, and asks one easy question.
          </p>
          <div className="mt-5 flex items-center gap-3 border-t border-line pt-4">
            <FitRing score={86} size={44} />
            <div className="min-w-0 flex-1">
              <div className="text-body font-semibold text-ink">Hot fit</div>
              <div className="truncate text-small text-muted">Judged against your brief</div>
            </div>
            <span className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-small font-semibold text-primary-ink">
              <Check className="size-4" aria-hidden /> Approve
            </span>
          </div>
        </div>
        <ol className="mt-5 grid grid-cols-5 gap-1 text-center" aria-label="What happens before you see a draft">
          {PIPELINE.map((step, i) => (
            <li key={step.label} className="flex flex-col items-center gap-1.5">
              <span className={cx("flex size-8 items-center justify-center rounded-full", i === PIPELINE.length - 1 ? "bg-primary text-primary-ink" : "bg-good-soft text-good")}>{step.icon}</span>
              <span className={cx("text-label", i === PIPELINE.length - 1 ? "font-semibold text-primary" : "text-muted")}>{step.label}</span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function Welcome({ name, goal, onGoal, onStart }: { name: string; goal: Goal; onGoal: (g: Goal) => void; onStart: () => void }) {
  const first = name ? name.split(" ")[0] : "";
  const icons: Record<Goal, ReactNode> = { market: <Radar className="size-5" />, list: <Inbox className="size-5" />, both: <Compass className="size-5" /> };
  return (
    <Frame>
      <div className="relative overflow-hidden">
        <div className="aurora" aria-hidden />
        <div className="relative mx-auto grid max-w-6xl items-center gap-10 px-4 py-10 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-14 lg:py-16">
          <div className="min-w-0">
            <Chip tone="primary" dot pulse>
              Setup takes about 6 minutes
            </Chip>
            <p className="mt-5 text-body font-semibold text-primary">Welcome{first ? `, ${first}` : ""}</p>
            <h1 className="mt-1 max-w-[20ch] text-display font-semibold text-ink">Outbound finds the companies, the right person and the first email. You just approve.</h1>
            <p className="mt-4 max-w-[52ch] text-[1.0625rem] text-muted">We do most of the typing: your company is drafted from your website, and your campaign from your company.</p>

            <div className="mt-8">
              <div className="text-body font-semibold text-ink">What do you want first?</div>
              <div role="radiogroup" aria-label="Your main goal" className="mt-3 space-y-2.5">
                {GOALS.map((g) => (
                  <button
                    key={g.key}
                    type="button"
                    role="radio"
                    aria-checked={goal === g.key}
                    onClick={() => onGoal(g.key)}
                    className={cx("press flex w-full items-start gap-3 rounded-2xl border p-4 text-left transition", goal === g.key ? "border-primary bg-primary-soft ring-2 ring-primary-line" : "border-line bg-surface hover:border-line-strong")}
                  >
                    <span className={cx("flex size-10 shrink-0 items-center justify-center rounded-xl", goal === g.key ? "bg-primary text-primary-ink" : "bg-surface-3 text-ink-2")}>{icons[g.key]}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-heading font-semibold text-ink">{g.label}</span>
                        {g.key === "market" && <Chip tone="primary">Recommended</Chip>}
                      </span>
                      <span className="mt-0.5 block text-small text-muted">{g.line}</span>
                    </span>
                    <span className={cx("mt-1 flex size-5 shrink-0 items-center justify-center rounded-full border", goal === g.key ? "border-primary bg-primary text-primary-ink" : "border-line-strong")} aria-hidden>
                      {goal === g.key && <Check className="size-3" />}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            <div className="mt-7">
              <Button size="lg" onClick={onStart}>
                Let's set up my engine <ArrowRight className="size-4" aria-hidden />
              </Button>
            </div>
            <ul className="mt-6 space-y-1.5 text-small text-muted">
              {["Nothing is sent without your approval: approved emails land in your Drafts.", "Country rules are applied for you.", "Opt-outs and bounces are handled automatically."].map((line) => (
                <li key={line} className="flex items-start gap-1.5">
                  <ShieldCheck className="mt-0.5 size-4 shrink-0 text-good-dot" aria-hidden /> {line}
                </li>
              ))}
            </ul>
          </div>
          <ExampleDraft />
        </div>
      </div>
    </Frame>
  );
}

function Celebration({ name, onBack }: { name: string; onBack: () => void }) {
  const { start } = useTour();
  const auto = useQuery({ queryKey: ["auto-discovery"], queryFn: () => ok(client.GET("/api/runs/auto-discovery")), refetchInterval: 15000 });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => ok(client.GET("/api/runs")), refetchInterval: 5000 });
  const live = runs.data?.find((r) => r.status === "running" || r.status === "queued");
  const first = name ? name.split(" ")[0] : "";
  return (
    <Frame>
      <div className="relative overflow-hidden">
        <Confetti />
        <div className="relative mx-auto max-w-3xl px-4 py-14 text-center sm:px-6">
          <Orb />
          <h1 className="mt-6 text-display font-semibold text-ink">Your engine is ready{first ? `, ${first}` : ""} 🎉</h1>
          <p className="mx-auto mt-3 max-w-[56ch] text-[1.0625rem] text-muted">
            {live ? "A run is working right now." : auto.data?.reason === "no_campaign" ? "Add who to reach and discovery starts by itself." : auto.data?.next_search ? `Discovery runs by itself; the next search is ${new Date(auto.data.next_search) <= new Date() ? "due now" : `at ${new Date(auto.data.next_search).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`}.` : "Discovery runs by itself about four times a day."}
          </p>

          <ol className="card mx-auto mt-10 max-w-xl space-y-5 p-6 text-left">
            {[
              ["Discovery finds companies that fit", "Each one is screened against your brief; only fits become leads."],
              ["Research, people and verified addresses", "Within minutes of a lead arriving, the next steps run on their own."],
              ["First drafts arrive in Review", "You read, edit or approve. Hot leads (fit above 80) come first."],
              ["Approved emails land in your Drafts", "Saved to your mailbox within 15 minutes. You press send."],
            ].map(([head, body], i) => (
              <li key={head} className="flex gap-4">
                <span className={cx("flex size-8 shrink-0 items-center justify-center rounded-full text-small font-bold", i === 0 && live ? "bg-working-dot text-white" : "bg-primary-soft text-primary")}>{i + 1}</span>
                <div>
                  <div className="font-semibold text-ink">{head}</div>
                  <div className="text-small text-muted">{body}</div>
                </div>
              </li>
            ))}
          </ol>

          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link to="/" className={buttonClass("primary", "lg")}>
              Go to Today <ArrowRight className="size-4" aria-hidden />
            </Link>
            <Button size="lg" variant="secondary" onClick={start}>
              <Compass className="size-4" aria-hidden /> Take the guided tour
            </Button>
          </div>
          <button type="button" data-tour="onboarding-steps" onClick={onBack} className="mt-4 text-small font-semibold text-muted hover:text-ink">
            Back to the setup steps
          </button>
        </div>
      </div>
    </Frame>
  );
}

/** A glowing orb with the four engine steps orbiting it. */
function Orb() {
  return (
    <svg width="180" height="180" viewBox="0 0 180 180" className="mx-auto" aria-hidden>
      <defs>
        <radialGradient id="orb" cx="40%" cy="35%">
          <stop offset="0" stopColor="#c7d2fe" />
          <stop offset="0.55" stopColor="var(--primary)" />
          <stop offset="1" stopColor="var(--violet)" />
        </radialGradient>
      </defs>
      <circle cx="90" cy="90" r="78" fill="none" stroke="var(--primary-line)" strokeDasharray="2 6" />
      <circle cx="90" cy="90" r="58" fill="none" stroke="var(--primary-line)" />
      <g className="origin-center animate-sweep" style={{ transformBox: "view-box", transformOrigin: "90px 90px", animationDuration: "14s" }}>
        {[0, 90, 180, 270].map((a) => (
          <circle key={a} cx={90 + 78 * Math.cos((a * Math.PI) / 180)} cy={90 + 78 * Math.sin((a * Math.PI) / 180)} r="6" fill="var(--surface)" stroke="var(--primary)" strokeWidth="2" />
        ))}
      </g>
      <circle cx="90" cy="90" r="34" fill="url(#orb)" className="animate-pulse-dot text-primary" />
    </svg>
  );
}

/** A short, light confetti burst. Skipped entirely with "reduce motion". */
export function Confetti() {
  const colours = ["var(--primary)", "var(--violet)", "var(--good-dot)", "var(--attention-dot)", "var(--working-dot)", "var(--error-dot)"];
  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden motion-reduce:hidden" aria-hidden>
      {Array.from({ length: 48 }, (_, i) => (
        <span
          key={i}
          className="absolute top-0 block h-2.5 w-1.5 rounded-sm"
          style={{
            left: `${(i * 37) % 100}%`,
            background: colours[i % colours.length],
            animation: `fall ${2.4 + (i % 7) * 0.25}s cubic-bezier(.2,.6,.4,1) ${(i % 12) * 0.08}s 1 both`,
            ["--dx" as string]: `${((i * 53) % 120) - 60}px`,
          }}
        />
      ))}
    </div>
  );
}
