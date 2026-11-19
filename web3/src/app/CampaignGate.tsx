/**
 * Day zero: shown in place of every page until the workspace has an active campaign that says
 * who it reaches (job titles and an ideal customer). Starter templates fill the form in one
 * click; "Suggest from my profile" asks the model, filling only empty fields. Saving updates the
 * workspace's existing campaign or creates one, exactly as web2 did.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Building2, MapPin, Rocket, Sparkles, Target, UserRound, Zap } from "lucide-react";
import { useState } from "react";
import { client, ok } from "../api/client";
import { cx } from "../lib/cx";
import { lines } from "../lib/format";
import { Button, Callout, Card, Field, Input, Problem, Textarea } from "../ui/core";
import { useToast } from "../ui/overlay";
import { useCurrent, useIsAdmin } from "./session";

/** Realistic starting points. They only pre-fill the form; nothing is saved until you press Save. */
export const STARTERS = [
  {
    key: "fintech",
    title: "UK fintech finance leaders",
    who: "CFO, VP Finance, Head of FP&A",
    where: "UK & Ireland · 25–250 staff",
    signal: "Raised money in the last 12 months",
    ruleOut: "Banks, agencies, companies on an enterprise ERP",
    titles: ["CFO", "VP Finance", "Head of FP&A", "Finance Director"],
    icp: "Venture-backed fintech and B2B SaaS companies in the UK and Ireland with 25 to 250 staff, a finance team of at least three, and a funding round in the last twelve months. Not banks, not agencies, not companies already using an enterprise ERP.",
  },
  {
    key: "saas",
    title: "Dutch SaaS founders",
    who: "Founder, CEO, Co-founder",
    where: "Netherlands · 10–80 staff",
    signal: "Hiring their first sales role",
    ruleOut: "Agencies and consultancies",
    titles: ["Founder", "CEO", "Co-founder"],
    icp: "Software-as-a-service start-ups headquartered in the Netherlands with 10 to 80 staff, selling to businesses, that are hiring their first account executive or sales lead. Not agencies or consultancies.",
  },
  {
    key: "recruitment",
    title: "Recruitment agencies in the Midlands",
    who: "Managing Director, Operations Director",
    where: "England · 5–50 staff",
    signal: "Opened a new desk or office",
    ruleOut: "Umbrella and payroll companies, franchise networks",
    titles: ["Managing Director", "Operations Director", "Director"],
    icp: "Independent recruitment agencies in the English Midlands with 5 to 50 staff that place permanent and contract candidates. Rule out umbrella and payroll companies and franchise networks.",
  },
] as const;

export function CampaignGate() {
  const admin = useIsAdmin();
  return (
    <div data-tour="campaign-gate" className="animate-rise">
      <div className="mb-3 hidden gap-3 sm:grid sm:grid-cols-4" aria-hidden>
        {[0, 1, 2, 3].map((n) => (
          <div key={n} className="h-12 rounded-t-2xl border border-b-0 border-dashed border-line bg-surface-2/60 px-4 pt-3">
            <div className="h-2 w-16 rounded-full bg-surface-3" />
          </div>
        ))}
      </div>
      <section className="relative -mt-3 mb-8 overflow-hidden rounded-2xl border border-line bg-surface px-6 py-10 text-center shadow-1 sm:px-10">
        <div className="aurora" aria-hidden />
        <div className="relative">
          <EmptyTrayArt />
          <h1 className="mx-auto mt-5 max-w-[24ch] text-display font-semibold text-ink">Your engine is ready. Tell it who to look for.</h1>
          <p className="mx-auto mt-3 max-w-[60ch] text-[1.0625rem] text-muted">
            Pick a starting campaign or describe your own. Outbound then finds companies that fit, researches them, and drafts first emails for you to review. Nothing is sent without your approval.
          </p>
          {admin && (
            <div className="mt-6">
              <Button size="lg" onClick={() => document.getElementById("campaign-form")?.scrollIntoView({ behavior: "smooth", block: "start" })}>
                <Rocket className="size-4" aria-hidden /> Create your campaign
              </Button>
            </div>
          )}
        </div>
      </section>
      {admin ? (
        <FirstCampaign />
      ) : (
        <Callout tone="attention" title="An admin has to set this up">
          This workspace has no campaign yet. Ask one of its admins to create it; everything opens as soon as they have.
        </Callout>
      )}
    </div>
  );
}

export function FirstCampaign({ onSaved }: { onSaved?: () => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const { workspace } = useCurrent();
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  const existing = campaigns.data?.find((c) => c.status === "active") ?? campaigns.data?.[0];
  const [picked, setPicked] = useState<string | null>(null);
  const [name, setName] = useState(`${workspace.name} outreach`);
  const [titles, setTitles] = useState("");
  const [icp, setIcp] = useState("");

  const use = (key: string) => {
    const s = STARTERS.find((x) => x.key === key)!;
    setPicked(key);
    setName(s.title);
    setTitles(s.titles.join("\n"));
    setIcp(s.icp);
    document.getElementById("campaign-form")?.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const suggest = useMutation({
    mutationFn: () => ok(client.POST("/api/setup/campaign-draft")),
    onSuccess: (found) => {
      if (!found.drafted) return;
      if (!titles.trim() && found.target_titles.length) setTitles(found.target_titles.join("\n"));
      if (!icp.trim() && found.icp_description) setIcp(found.icp_description);
    },
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { name: name.trim(), target_titles: lines(titles), icp_description: icp.trim() || null };
      return existing
        ? ok(client.PATCH("/api/settings/campaigns/{campaign_id}", { params: { path: { campaign_id: existing.id } }, body }))
        : ok(client.POST("/api/settings/campaigns", { body: { ...body, min_fit_score: 60, research_questions: [], cadence_days: [0, 3, 8] } }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
      void queryClient.invalidateQueries({ queryKey: ["setup"] });
      toast({ tone: "good", title: "Campaign saved", body: "Discovery can now look for companies that fit it." });
      onSaved?.();
    },
  });
  const ready = name.trim() && lines(titles).length > 0 && icp.trim().length > 20;

  return (
    <div className="space-y-6">
      <div>
        <div className="mb-3 flex items-baseline justify-between gap-3">
          <h2 className="text-heading font-semibold text-ink">Start from a template</h2>
          <span className="text-small text-muted">One click fills the form below. You can change everything.</span>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {STARTERS.map((s) => (
            <button
              key={s.key}
              type="button"
              onClick={() => use(s.key)}
              className={cx("card card-hover press group flex flex-col p-5 text-left", picked === s.key && "border-primary ring-2 ring-primary-line")}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="text-heading font-semibold text-ink">{s.title}</div>
                <Target className="size-4 shrink-0 text-primary" aria-hidden />
              </div>
              <dl className="mt-3 space-y-1.5 text-small text-muted">
                <div className="flex items-start gap-2">
                  <dt className="sr-only">Who</dt>
                  <UserRound className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <dd className="text-ink-2">{s.who}</dd>
                </div>
                <div className="flex items-start gap-2">
                  <dt className="sr-only">Where</dt>
                  <MapPin className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <dd>{s.where.split(" · ")[0]}</dd>
                </div>
                <div className="flex items-start gap-2">
                  <dt className="sr-only">Size</dt>
                  <Building2 className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <dd>{s.where.split(" · ")[1]}</dd>
                </div>
              </dl>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <span className="inline-flex items-center gap-1 rounded-lg bg-attention-soft px-2 py-1 text-label font-medium text-attention">
                  <Zap className="size-3.5" aria-hidden /> Signal: {s.signal}
                </span>
                <span className="inline-flex items-center gap-1 rounded-lg bg-surface-3 px-2 py-1 text-label font-medium text-muted">
                  <Ban className="size-3.5" aria-hidden /> Rule-out: {s.ruleOut}
                </span>
              </div>
              <div className="mt-auto pt-4">
                <span className="flex w-full justify-center rounded-lg border border-line-strong bg-surface px-3 py-2 text-small font-semibold text-ink group-hover:border-primary group-hover:text-primary">
                  {picked === s.key ? "Filled in below ✓" : "Use this"}
                </span>
              </div>
            </button>
          ))}
        </div>
      </div>

      <Card className="p-6" id="campaign-form">
        <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-heading font-semibold text-ink">Your campaign</h2>
            <p className="text-body text-muted">Who you want to reach. Research, scoring and discovery all read this.</p>
          </div>
          <Button variant="soft" busy={suggest.isPending} onClick={() => suggest.mutate()}>
            <Sparkles className="size-4" aria-hidden /> Suggest from my profile
          </Button>
        </div>
        {suggest.data && !suggest.data.drafted && (
          <Callout tone="neutral" className="mb-4">
            {suggest.data.reason === "profile_empty" ? "Confirm your company profile first; the suggestion is written from it." : "No suggestion could be written just now. Fill it in yourself; you can change it later."}
          </Callout>
        )}
        <div className="grid gap-5 md:grid-cols-2">
          <Field label="Campaign name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Job titles to reach" hint="One per line. The first ones count most.">
            <Textarea rows={4} value={titles} onChange={(e) => setTitles(e.target.value)} placeholder={"CFO\nVP Finance"} />
          </Field>
          <Field label="Your ideal customer" hint="Size, place, what they do, and who you do not want. A model turns this into a brief you can edit." className="md:col-span-2">
            <Textarea rows={5} value={icp} onChange={(e) => setIcp(e.target.value)} />
          </Field>
        </div>
        <Problem error={save.error} className="mt-4" />
        <div className="mt-5 flex justify-end">
          <Button size="lg" busy={save.isPending} disabled={!ready} onClick={() => save.mutate()}>
            Save campaign
          </Button>
        </div>
      </Card>
    </div>
  );
}

/** An empty tray with a small radar sweeping above it: "nothing yet, but it is looking". */
function EmptyTrayArt() {
  return (
    <svg width="168" height="112" viewBox="0 0 168 112" className="mx-auto" aria-hidden>
      <defs>
        <linearGradient id="tray" x1="0" x2="1">
          <stop offset="0" stopColor="var(--primary)" />
          <stop offset="1" stopColor="var(--violet)" />
        </linearGradient>
      </defs>
      <g className="origin-[84px_40px] animate-sweep" style={{ transformBox: "view-box" }}>
        <path d="M84 40 L84 6 A34 34 0 0 1 113 23 Z" fill="var(--primary-soft)" />
      </g>
      <circle cx="84" cy="40" r="34" fill="none" stroke="var(--primary-line)" strokeDasharray="3 5" />
      <circle cx="84" cy="40" r="18" fill="none" stroke="var(--primary-line)" />
      <circle cx="84" cy="40" r="3" fill="url(#tray)" />
      <circle cx="104" cy="26" r="2.5" fill="var(--good-dot)" className="animate-pulse-dot text-good-dot" />
      <path d="M28 78 h112 l-10 26 h-92 z" fill="var(--surface-2)" stroke="url(#tray)" strokeWidth="2" strokeLinejoin="round" />
      <path d="M50 78 l10 12 h48 l10 -12" fill="none" stroke="url(#tray)" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  );
}
