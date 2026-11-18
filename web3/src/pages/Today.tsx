/**
 * Today: wins first. The emails ready to approve (with the top few right here), then the hot
 * leads to message on LinkedIn, then the week's results. Only after that does it say what the
 * engine screened out (normal) and what needs a decision. Every number is from the live API.
 * Sections fold; the first is open.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, Check, CheckCircle2, Filter, Flame, Play, Radar, Sparkles, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { client, ok, type Schemas } from "../api/client";
import { describe as describeNotice } from "../app/Bell";
import { useCounts } from "../app/Shell";
import { useCurrent } from "../app/session";
import { cx } from "../lib/cx";
import { ago, percent } from "../lib/format";
import { describeHold } from "../lib/status";
import { useSetup } from "../lib/setup";
import { LinkedInDraftCard } from "../components/LinkedInDraft";
import { isViewing } from "../app/session";
import { Avatar, Button, buttonClass, Card, Chip, Empty, Skeleton } from "../ui/core";
import { useToast } from "../ui/overlay";
import { Section, SectionGroup } from "../ui/sections";
import { CountUp, Delta, Ring, Sparkline } from "../ui/viz";

const SOURCE_LABEL: Record<string, string> = { yc_directory: "YC directory", companies_house: "Companies House", exa: "Exa", articles: "Web lists" };

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

function greeting(name: string) {
  const h = new Date().getHours();
  const part = h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  return name ? `${part}, ${name.split(" ")[0]}` : part;
}

export function TodayPage() {
  const { me } = useCurrent();
  const counts = useCounts();
  const status = counts.status.data;
  const review = useQuery({ queryKey: ["review"], queryFn: () => ok(client.GET("/api/review")), refetchInterval: 15000 });
  const daily = useQuery({ queryKey: ["daily", 14], queryFn: () => ok(client.GET("/api/reports/daily", { params: { query: { days: 14 } } })), refetchInterval: 60000 });
  const quality = useQuery({ queryKey: ["quality"], queryFn: () => ok(client.GET("/api/reports/quality")) });
  const auto = useQuery({ queryKey: ["auto-discovery"], queryFn: () => ok(client.GET("/api/runs/auto-discovery")), refetchInterval: 30000 });
  const setup = useSetup();
  const { workspace } = useCurrent();
  const viewing = isViewing(workspace);
  const hotLeads = useQuery({ queryKey: ["linkedin", "drafted", "hot", 3], queryFn: () => ok(client.GET("/api/linkedin", { params: { query: { state: "drafted", hot: true, limit: 3 } } })), refetchInterval: 30000 });

  const days = daily.data?.days ?? [];
  const thisWeek = days.slice(-7);
  const lastWeek = days.slice(-14, -7);
  const pick = (k: keyof Schemas["DayOut"]) => (rows: Schemas["DayOut"][]) => rows.map((r) => Number(r[k]));
  const reviewedToday = days.at(-1)?.reviewed ?? 0;
  const waiting = review.data ?? [];
  const hot = waiting.filter((i) => i.company.hot).length;
  // The best three first: hot leads, then by fit. Anything with a skipped check is approved in Review.
  const top = [...waiting].sort((a, b) => Number(b.company.hot) - Number(a.company.hot) || (b.company.fit_score ?? 0) - (a.company.fit_score ?? 0)).slice(0, 3);

  return (
    <div className="space-y-6">
      {setup.data && !setup.data.done && setup.data.next && (
        <Card className="flex flex-wrap items-center gap-4 border-primary-line bg-primary-soft p-4">
          <Sparkles className="size-5 text-primary" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="font-semibold text-ink">Finish setting up: {setup.data.next.title}</div>
            <div className="text-small text-muted">{setup.data.next.detail}</div>
          </div>
          <Link to="/onboarding" className={buttonClass("primary", "sm")}>
            Continue setup <ArrowRight className="size-4" aria-hidden />
          </Link>
        </Card>
      )}

      {/* Bento: the hero on the left, the engine and progress on the right. */}
      <div className="grid gap-5 lg:grid-cols-3">
        <section data-tour="today-hero" className="relative overflow-hidden rounded-2xl border border-line bg-surface p-5 sm:p-8 lg:col-span-2">
          <div className="aurora opacity-80" aria-hidden />
          <div className="relative flex h-full flex-col">
            <div className="text-body font-medium text-muted">{greeting(me.user.name)}</div>
            <h1 className="mt-2 max-w-[26ch] text-display font-semibold text-ink">
              {counts.review > 0 ? (
                <>
                  <CountUp value={counts.review} /> {counts.review === 1 ? "email is" : "emails are"} ready for you
                </>
              ) : hotLeads.data?.total ? (
                <>
                  <CountUp value={hotLeads.data.total} /> hot {hotLeads.data.total === 1 ? "lead is" : "leads are"} ready to message
                </>
              ) : (
                "You are all caught up."
              )}
            </h1>
            <p className="mt-3 max-w-[60ch] text-[1.0625rem] text-muted">
              {counts.review > 0 ? (
                <>
                  {hot > 0 && (
                    <>
                      <Flame className="inline size-4 text-attention-dot" aria-hidden /> {hot} {hot === 1 ? "is a hot lead" : "are hot leads"} (fit above 80) ·{" "}
                    </>
                  )}
                  Approve them and they land in your mailbox as drafts. Nothing is sent without you.
                </>
              ) : (
                <>New emails appear here as the engine writes them. {auto.data?.next_search ? `Next discovery ${relative(auto.data.next_search)}.` : ""}</>
              )}
            </p>
            {top.length > 0 && (
              <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3" data-tour="ready-drafts">
                {top.map((item) => (
                  <DraftPreview key={item.message.id} item={item} readOnly={viewing} />
                ))}
              </div>
            )}
            <div className="mt-auto flex flex-wrap items-center gap-3 pt-6">
              {counts.review > 0 ? (
                <Link to="/review" className={buttonClass("primary", "lg")} data-tour="start-reviewing">
                  <Play className="size-4" aria-hidden /> Start reviewing
                  <span className="tnum rounded-md bg-white/20 px-1.5 text-small">{counts.review}</span>
                </Link>
              ) : (
                <Link to="/runs" className={buttonClass("secondary", "lg")}>
                  <Radar className="size-4" aria-hidden /> See discovery
                </Link>
              )}
              {counts.attention > 0 && (
                <Link to="/attention" className={buttonClass("ghost", "lg")}>
                  {counts.attention} need{counts.attention === 1 ? "s" : ""} a decision <ArrowRight className="size-4" aria-hidden />
                </Link>
              )}
            </div>
          </div>
        </section>

        <div className="grid gap-5">
          <Card className="flex items-center gap-5 p-5" data-tour="review-progress">
            <Ring share={counts.review + reviewedToday ? reviewedToday / (counts.review + reviewedToday) : 0} size={76} stroke={8} tone="good" label={reviewedToday} title={`${reviewedToday} reviewed today`} />
            <div className="min-w-0">
              <div className="text-heading font-semibold text-ink">Reviewed today</div>
              <div className="text-small text-muted">
                {reviewedToday} done{counts.review ? `, ${counts.review} to go` : ""}
              </div>
              {(daily.data?.review_streak ?? 0) > 1 && (
                <Chip tone="attention" className="mt-2">
                  <Flame className="size-3.5" aria-hidden /> {daily.data!.review_streak}-day review streak
                </Chip>
              )}
            </div>
          </Card>
          <EngineCard auto={auto.data} />
        </div>
      </div>

      <HotLeads data={hotLeads.data} loading={hotLeads.isPending} readOnly={viewing} />

      {/* The week's wins, with the last two weeks behind them. */}
      <div data-tour="kpis" className="grid grid-cols-1 gap-3 sm:grid-cols-3 sm:gap-4">
        <Kpi
          label="Emails approved this week"
          value={sum(pick("approved")(thisWeek))}
          before={sum(pick("approved")(lastWeek))}
          series={pick("approved")(days)}
          why="Each approved email is one draft in your mailbox, ready to send."
          tone="good"
          loading={daily.isPending}
        />
        <Kpi
          label="Approved without edits"
          value={quality.data?.unedited_share != null ? Math.round(quality.data.unedited_share * 100) : null}
          format={(n) => `${Math.round(n)}%`}
          footer={<span className="text-small text-muted">of {quality.data?.sent ?? 0} sent · target 80%</span>}
          why="How often the first draft was good enough to send as written. The engine aims for 8 in 10."
          tone="good"
          loading={quality.isPending}
        />
        <Kpi
          label="New leads this week"
          value={sum(pick("leads")(thisWeek))}
          before={sum(pick("leads")(lastWeek))}
          series={pick("leads")(days)}
          why="Companies that became leads, by discovery or by you."
          loading={daily.isPending}
        />
      </div>

      <SectionGroup storageKey="today">
        <BehindTheScenes status={status} />
        <NeedsYou status={status} />
        <ActiveCampaign />
        <Sources />
        <Activity />
      </SectionGroup>
    </div>
  );
}

function relative(iso: string) {
  const ms = new Date(iso).getTime() - Date.now();
  if (ms <= 0) return "is due now";
  const minutes = Math.round(ms / 60000);
  return minutes < 60 ? `in ${minutes} min` : `in ${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

const AUTO_REASON: Record<string, string> = {
  off: "Automatic discovery is switched off.",
  no_campaign: "Waiting for an active campaign with an ideal customer.",
  no_credits: "No AI credits left this period.",
  run_in_progress: "A run is in progress.",
  review_full: "Paused: Review holds enough drafts. Work through them and it starts again.",
  backlog: "Paused: plenty of leads still wait for their emails.",
};

function EngineCard({ auto }: { auto?: Schemas["AutoDiscoveryOut"] }) {
  const share = auto ? Math.min(1, auto.waiting_for_review / Math.max(1, auto.review_limit)) : 0;
  return (
    <Card className="p-5" data-tour="engine">
      <div className="flex items-center gap-2">
        <span className={cx("size-2 rounded-full", auto?.reason && auto.reason !== "not_yet" ? "bg-attention-dot" : "bg-good-dot animate-pulse-dot text-good-dot")} aria-hidden />
        <span className="text-heading font-semibold text-ink">Discovery</span>
        {auto && <span className="ml-auto text-small text-muted">{auto.per_day}× a day</span>}
      </div>
      {!auto ? (
        <Skeleton shape="stat" className="mt-3" />
      ) : (
        <>
          <p className="mt-2 text-small text-ink-2">
            {auto.reason && auto.reason !== "not_yet" ? AUTO_REASON[auto.reason] : auto.next_search ? `Next search ${relative(auto.next_search)}.` : "A search is due now."}
            {auto.last_search && <span className="text-muted"> Last one {ago(auto.last_search)}.</span>}
          </p>
          <div className="mt-3">
            <div className="flex justify-between text-label text-muted">
              <span>Drafts in Review</span>
              <span className="tnum">
                {auto.waiting_for_review} / {auto.review_limit}
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-3">
              <div className={cx("h-full rounded-full transition-[width] duration-700", share >= 1 ? "bg-attention-dot" : "bg-primary")} style={{ width: `${share * 100}%` }} />
            </div>
            <div className="mt-1 text-label text-faint">Discovery pauses at {auto.review_limit} so you are never buried.</div>
          </div>
        </>
      )}
    </Card>
  );
}

function Kpi({
  label,
  value,
  before,
  series,
  format,
  why,
  footer,
  tone = "primary",
  invert,
  loading,
}: {
  label: string;
  value: number | null;
  before?: number;
  series?: number[];
  format?: (n: number) => string;
  why: string;
  footer?: ReactNode;
  tone?: "primary" | "good" | "attention";
  invert?: boolean;
  loading?: boolean;
}) {
  return (
    <Card hover className="group relative p-4 sm:p-5" title={why}>
      <div className="text-small font-medium text-muted">{label}</div>
      {loading ? (
        <Skeleton shape="stat" className="mt-3" />
      ) : (
        <>
          <div className="mt-2 flex flex-wrap items-end justify-between gap-2">
            <div className="text-[2rem] leading-none font-semibold tracking-tight text-ink">{value === null ? "–" : <CountUp value={value} format={format} />}</div>
            {series && <Sparkline values={series} tone={tone} className="hidden sm:block" />}
          </div>
          <div className="mt-3">{footer ?? (before !== undefined && value !== null ? <Delta now={value} before={before} invert={invert} unit="" /> : null)}</div>
          <p className="mt-2 hidden text-label text-muted group-hover:block">{why}</p>
        </>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ sections

function NeedsYou({ status }: { status?: Schemas["StatusOut"] }) {
  const usage = useQuery({ queryKey: ["usage"], queryFn: () => ok(client.GET("/api/usage")) });
  const waitingRows = useQuery({ queryKey: ["waiting"], queryFn: () => ok(client.GET("/api/targets/waiting")) });
  // A catch-all being resolved waits for the resolver, not for you.
  const held = Object.entries(status?.held ?? {}).filter(([reason, n]) => n > 0 && reason !== "catch_all_resolving");
  const heldCount = held.reduce((a, [, n]) => a + n, 0);
  const stopped = Math.max(0, (status?.buckets?.decision ?? 0) - heldCount);
  const credit = Object.values(usage.data?.waiting_leads ?? {}).reduce((a, b) => a + b, 0) + (usage.data?.waiting_rows ?? 0);
  const sites = waitingRows.data?.length ?? 0;
  const items = [
    ...held.map(([reason, n]) => ({ key: reason, tone: "stopped" as const, label: describeHold(reason).label, text: `${n} lead${n === 1 ? "" : "s"}. ${describeHold(reason).why || "Waiting for your decision."}`, to: "/attention" })),
    ...(stopped ? [{ key: "stopped", tone: "error" as const, label: "Stopped", text: `${stopped} lead${stopped === 1 ? "" : "s"} stopped after every try. Check the cause, then retry.`, to: "/attention" }] : []),
    ...(sites ? [{ key: "sites", tone: "stopped" as const, label: "Websites to confirm", text: `${sites} uploaded row${sites === 1 ? "" : "s"} need${sites === 1 ? "s" : ""} a website before research.`, to: "/attention" }] : []),
    ...(credit ? [{ key: "credit", tone: "stopped" as const, label: "Waiting for credits", text: `${credit} lead${credit === 1 ? "" : "s"} paused until credits renew or more are granted.`, to: "/attention" }] : []),
  ];
  const total = heldCount + stopped + sites + credit;
  return (
    <Section
      id="needs"
      tour="needs-you"
      icon={<TriangleAlert className="size-5" />}
      title="Needs a decision"
      summary={items.length ? items.map((i) => i.label).join(" · ") : "Nothing needs a decision."}
      chip={items.length ? <Chip tone="stopped">{total} to decide</Chip> : <Chip tone="good">All clear</Chip>}
    >
      {items.length === 0 ? (
        <Empty art={<CheckCircle2 className="size-10 text-good-dot" />} title="Nothing needs a decision ✨">
          Holds and stopped steps show up here the moment they need you.
        </Empty>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {items.map((item) => (
            <Link key={item.key} to={item.to} className="card card-hover block p-4">
              <Chip tone={item.tone}>{item.label}</Chip>
              <p className="mt-2 text-body text-ink-2">{item.text}</p>
              <span className="mt-2 inline-flex items-center gap-1 text-small font-semibold text-primary">
                Open <ArrowRight className="size-3.5" aria-hidden />
              </span>
            </Link>
          ))}
        </div>
      )}
    </Section>
  );
}

/**
 * Where the companies went, in plain words. Most are meant to drop out: screening them out is
 * how the list stays sharp, so it is grey, not red.
 */
function BehindTheScenes({ status }: { status?: Schemas["StatusOut"] }) {
  const b = status?.buckets ?? {};
  const total = sum(Object.values(b));
  const reached = (b.ready ?? 0) + (b.done ?? 0);
  const parts = [
    { key: "ready", label: "Reached you", n: reached, bucket: undefined as string | undefined, color: "var(--good-dot)" },
    { key: "working", label: "Being worked on", n: b.working ?? 0, bucket: "working", color: "var(--working-dot)" },
    { key: "decision", label: "Needs a decision", n: b.decision ?? 0, bucket: "decision", color: "var(--attention-dot)" },
    { key: "screened_out", label: "Screened out", n: b.screened_out ?? 0, bucket: "screened_out", color: "var(--surface-3)" },
  ];
  return (
    <Section
      id="behind"
      tour="pipeline"
      icon={<Filter className="size-5" />}
      title="Behind the scenes"
      summary={total ? `${total} companies looked at · ${reached} reached you · ${b.screened_out ?? 0} screened out (normal)` : "Nothing looked at yet."}
      chip={<Chip tone="primary">{total} looked at</Chip>}
    >
      {total === 0 ? (
        <Empty title="Nothing yet">Companies you add or discovery finds appear here as they are looked at.</Empty>
      ) : (
        <>
          <div className="flex h-3 overflow-hidden rounded-full bg-surface-3" aria-label="Where the companies went">
            {parts.filter((p) => p.n > 0).map((p) => (
              <span key={p.key} style={{ width: `${(p.n / total) * 100}%`, background: p.color }} title={`${p.label}: ${p.n}`} />
            ))}
          </div>
          <ul className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {parts.map((p) => (
              <li key={p.key}>
                <Link to="/leads" search={p.bucket ? { bucket: p.bucket } : { bucket: "done" }} className="block rounded-xl border border-line p-3 hover:bg-surface-2">
                  <div className="flex items-center gap-2 text-small text-muted">
                    <span className="size-2.5 rounded-full" style={{ background: p.color }} aria-hidden /> {p.label}
                  </div>
                  <div className="tnum mt-1 text-[1.5rem] font-semibold text-ink">{p.n}</div>
                </Link>
              </li>
            ))}
          </ul>
          <p className="mt-4 max-w-[70ch] text-small text-muted">
            Most companies are meant to drop out: they do not fit your brief, nobody suitable works there, or no address could be proven. Screening them out is how the engine keeps your list sharp, so a long grey bar is a sign it works.
          </p>
        </>
      )}
    </Section>
  );
}

function ActiveCampaign() {
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  const fit = useQuery({ queryKey: ["fit"], queryFn: () => ok(client.GET("/api/reports/fit")) });
  const active = campaigns.data?.find((c) => c.status === "active");
  const brief = (active?.icp_brief ?? {}) as { summary?: string; must_haves?: { text: string }[]; buying_signals?: string[]; disqualifiers?: string[]; regions?: string[]; size_range?: string };
  const bands = fit.data?.bands ?? [];
  const peak = Math.max(1, ...bands.map((b) => b.count));
  const keep = fit.data?.min_fit_score ?? 60;
  const above = bands.filter((b) => b.start >= keep).reduce((a, b) => a + b.count, 0);
  return (
    <Section
      id="campaign"
      title={active ? `Active campaign: ${active.name}` : "Active campaign"}
      summary={active ? `${active.target_titles.slice(0, 3).join(", ")}${brief.regions?.length ? ` · ${brief.regions.join(", ")}` : ""}${fit.data ? ` · ${above} of ${fit.data.scored} scored pass the fit gate` : ""}` : "No active campaign."}
      chip={active ? <Chip tone="good" dot pulse>Active</Chip> : undefined}
      actions={
        <Link to="/campaigns" className={buttonClass("secondary", "sm")}>
          Edit brief
        </Link>
      }
    >
      {!active ? (
        <Empty title="No active campaign" action={<Link to="/campaigns" className={buttonClass("primary", "sm")}>Open Campaigns</Link>}>Create one, or switch one on, under Campaigns.</Empty>
      ) : (
        <div className="grid gap-6 lg:grid-cols-5">
          <div className="space-y-4 lg:col-span-3">
            {brief.summary && <p className="max-w-[75ch] text-body text-ink-2">{brief.summary}</p>}
            <BriefChips label="Must-haves" tone="primary" items={(brief.must_haves ?? []).map((m) => m.text)} />
            <BriefChips label="Signals" tone="good" items={brief.buying_signals ?? []} />
            <BriefChips label="Rule-outs" tone="error" items={brief.disqualifiers ?? []} />
          </div>
          <div className="lg:col-span-2">
            <div className="flex items-baseline justify-between">
              <div className="text-small font-semibold text-ink">Fit scores</div>
              <div className="text-label text-muted">keep at {keep}+</div>
            </div>
            <div className="mt-3 flex h-32 items-end gap-1">
              {bands.map((b) => (
                <div key={b.start} className="flex flex-1 flex-col items-center justify-end gap-1" title={`${b.start}–${b.start === 90 ? 100 : b.start + 9}: ${b.count}`}>
                  <div className="w-full rounded-t-md transition-[height] duration-700" style={{ height: `${(b.count / peak) * 100}%`, minHeight: b.count ? 4 : 0, background: b.start >= keep ? "var(--primary)" : "var(--surface-3)" }} />
                </div>
              ))}
            </div>
            <div className="mt-1 flex justify-between text-label text-faint">
              <span>0</span>
              <span>50</span>
              <span>100</span>
            </div>
            {fit.data && fit.data.unscored > 0 && <p className="mt-2 text-label text-muted">{fit.data.unscored} not scored yet.</p>}
          </div>
        </div>
      )}
    </Section>
  );
}

function BriefChips({ label, items, tone }: { label: string; items: string[]; tone: "primary" | "good" | "error" }) {
  if (!items.length) return null;
  return (
    <div>
      <div className="mb-1.5 text-label font-semibold tracking-wide text-faint uppercase">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((t) => (
          <Chip key={t} tone={tone} className="h-auto py-1 whitespace-normal">
            {t}
          </Chip>
        ))}
      </div>
    </div>
  );
}

function Sources() {
  const sources = useQuery({ queryKey: ["sources"], queryFn: () => ok(client.GET("/api/reports/sources")) });
  const rows = sources.data ?? [];
  const best = rows[0];
  return (
    <Section
      id="sources"
      title="Where good leads come from"
      summary={best ? `${SOURCE_LABEL[best.source] ?? best.source} leads pass the fit gate most often (${percent(best.rate)}) · last ${best.days} days` : "No discovery history yet."}
    >
      {rows.length === 0 ? (
        <Empty title="No discovery yet" action={<Link to="/runs" className={buttonClass("secondary", "sm")}>Start a run</Link>}>After the first runs, each source's record shows here, and discovery asks the best ones first.</Empty>
      ) : (
        <div className="space-y-3">
          {rows.map((r) => (
            <div key={r.source} className="grid grid-cols-[140px_1fr_auto] items-center gap-4">
              <span className="text-body font-medium text-ink">{SOURCE_LABEL[r.source] ?? r.source}</span>
              <div className="h-2.5 overflow-hidden rounded-full bg-surface-3">
                <div className="h-full rounded-full bg-gradient-to-r from-primary to-violet transition-[width] duration-700" style={{ width: `${Math.max(2, r.rate * 100)}%` }} />
              </div>
              <span className="tnum text-small text-muted">
                {percent(r.rate)} · {r.qualified}/{r.leads} leads · {r.found} named
              </span>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

function Activity() {
  const notices = useQuery({ queryKey: ["notifications"], queryFn: () => ok(client.GET("/api/me/notifications")), refetchInterval: 30000 });
  const { workspace } = useCurrent();
  const items = (notices.data?.items ?? []).filter((n) => !n.workspace_id || n.workspace_id === workspace.id).slice(0, 8);
  return (
    <Section id="activity" title="What happened" summary={items[0] ? `${describeNotice(items[0]).text} · ${ago(items[0].created_at)}` : "Nothing yet."}>
      {items.length === 0 ? (
        <Empty title="Quiet so far" action={<Link to="/targets" className={buttonClass("secondary", "sm")}>Add leads</Link>}>Runs, drafts and hot leads are reported here as they happen.</Empty>
      ) : (
        <ol className="relative space-y-4 border-l border-line pl-5">
          {items.map((n) => {
            const d = describeNotice(n);
            const Icon = d.icon;
            return (
              <li key={n.id} className="relative">
                <span className="absolute top-0.5 -left-[29px] flex size-6 items-center justify-center rounded-full border border-line bg-surface text-primary">
                  <Icon className="size-3.5" aria-hidden />
                </span>
                <div className={cx("text-body", !n.read ? "font-semibold text-ink" : "text-ink-2")}>{d.text}</div>
                <div className="text-label text-muted">{ago(n.created_at)}</div>
              </li>
            );
          })}
        </ol>
      )}
    </Section>
  );
}


/** One email ready to approve: who, why it is worth sending, the start of it, and one click. */
function DraftPreview({ item, readOnly }: { item: Schemas["ReviewItemOut"]; readOnly: boolean }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const name = item.company.name ?? item.company.domain;
  const body = item.message.final_body ?? item.message.generated_body;
  // A check that was skipped needs a deliberate "approve anyway", which Review asks for.
  const needsReview = (item.skips ?? []).length > 0 || item.flagged;
  const approve = useMutation({
    mutationFn: () => ok(client.POST("/api/review/{message_id}/approve", { params: { path: { message_id: item.message.id } }, body: { edited_body: null, row_version: item.message.row_version, acknowledge_skips: false } })),
    onSuccess: () => {
      toast({ tone: "good", title: `Approved · ${name}`, body: "It will be saved to your mailbox as a draft within 15 minutes." });
      for (const key of ["review", "status", "daily", "quality", "companies"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  return (
    <Card className="flex flex-col gap-2 p-4">
      <div className="flex items-center gap-2.5">
        <Avatar name={name} />
        <div className="min-w-0 flex-1">
          <div className="truncate font-semibold text-ink">{name}</div>
          <div className="truncate text-small text-muted">{item.contact.title ?? "Decision-maker"}</div>
        </div>
        {item.company.hot && (
          <Chip tone="attention" title="A fit score above 80">
            <Flame className="size-3.5" aria-hidden /> {item.company.fit_score}
          </Chip>
        )}
      </div>
      <div className="font-semibold text-ink">{item.message.subject}</div>
      <p className="line-clamp-2 text-small text-muted">{body}</p>
      <div className="mt-auto flex gap-2 pt-1">
        {!readOnly && !needsReview && (
          <Button size="sm" busy={approve.isPending} onClick={() => approve.mutate()}>
            <Check className="size-4" aria-hidden /> Approve
          </Button>
        )}
        <Link to="/review" search={{ message: item.message.id }} className={buttonClass(needsReview ? "primary" : "secondary", "sm")}>
          {needsReview ? "Check and approve" : "Open"}
        </Link>
      </div>
    </Card>
  );
}

/** The hot leads whose LinkedIn message is written, with the same copy-and-open buttons as the LinkedIn page. */
function HotLeads({ data, loading, readOnly }: { data?: Schemas["LinkedInDraftPage"]; loading: boolean; readOnly: boolean }) {
  const queryClient = useQueryClient();
  const refresh = () => {
    for (const key of ["linkedin", "companies", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  if (loading) return <Skeleton shape="stat" />;
  if (!data || data.items.length === 0) return null;
  return (
    <section data-tour="hot-leads" aria-labelledby="hot-leads-title">
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <h2 id="hot-leads-title" className="flex items-center gap-2 text-heading font-semibold text-ink">
          <Flame className="size-5 text-attention-dot" aria-hidden /> Hot leads: reach them on LinkedIn
        </h2>
        <Chip tone="attention">
          {data.total} message{data.total === 1 ? "" : "s"} written
        </Chip>
        <Link to="/linkedin" className="ml-auto text-small font-semibold text-primary hover:underline">
          See all <ArrowRight className="inline size-3.5" aria-hidden />
        </Link>
      </div>
      <p className="mb-3 max-w-[70ch] text-small text-muted">A connection note is ready for each. Some have no email we could prove, so LinkedIn is the way in. Copy it and paste it into their profile yourself: nothing is sent from here.</p>
      <div className="grid gap-4 lg:grid-cols-3">
        {data.items.map((row) => (
          <Card key={row.item.id} title={<Link to="/leads/$companyId" params={{ companyId: row.item.company_id }} className="hover:underline">{row.company_name ?? row.domain}</Link>} subtitle={[row.person, row.title].filter(Boolean).join(" · ") || undefined}>
            <LinkedInDraftCard draft={row.item} person={row.person} profile={row.profile} readOnly={readOnly} onChanged={refresh} />
          </Card>
        ))}
      </div>
    </section>
  );
}
