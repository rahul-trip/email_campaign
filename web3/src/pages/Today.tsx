/**
 * Today: what waits on you, how the engine is doing, and what changed — every number from the
 * live API (status, review queue, daily counts, quality, auto-discovery, credits, notifications,
 * fit bands, source yields, the active campaign). Sections fold; the first is open.
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, CheckCircle2, Flame, Inbox, Play, Radar, Sparkles, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { client, ok, type Schemas } from "../api/client";
import { describe as describeNotice } from "../app/Bell";
import { useCounts } from "../app/Shell";
import { useCurrent } from "../app/session";
import { cx } from "../lib/cx";
import { ago, percent, usd } from "../lib/format";
import { describeHold, leadStatus } from "../lib/status";
import { useSetup } from "../lib/setup";
import { buttonClass, Card, Chip, Empty, Skeleton } from "../ui/core";
import { Section, SectionGroup } from "../ui/sections";
import { CountUp, Delta, Ring, Sparkline } from "../ui/viz";

const STAGES = ["new", "researched", "qualified", "contacts_found", "email_ready", "copy_ready", "approved", "in_sequence", "replied"] as const;
const STAGE_COLOR: Record<string, string> = {
  new: "var(--stopped-dot)",
  researched: "var(--working-dot)",
  qualified: "var(--primary)",
  contacts_found: "var(--violet)",
  email_ready: "#14b8a6",
  copy_ready: "var(--attention-dot)",
  approved: "var(--good-dot)",
  in_sequence: "#22c55e",
  replied: "#16a34a",
};
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

  const days = daily.data?.days ?? [];
  const thisWeek = days.slice(-7);
  const lastWeek = days.slice(-14, -7);
  const pick = (k: keyof Schemas["DayOut"]) => (rows: Schemas["DayOut"][]) => rows.map((r) => Number(r[k]));
  const reviewedToday = days.at(-1)?.reviewed ?? 0;
  const waiting = review.data ?? [];
  const oldest = waiting.map((i) => i.message.created_at).filter((t): t is string => !!t).sort()[0] ?? null;
  const hot = waiting.filter((i) => i.company.hot).length;

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
            <h1 className="mt-2 max-w-[24ch] text-display font-semibold text-ink">
              {counts.review > 0 ? (
                <>
                  <CountUp value={counts.review} /> {counts.review === 1 ? "draft is" : "drafts are"} waiting for you
                </>
              ) : (
                "Review is clear. Nice work."
              )}
            </h1>
            <p className="mt-3 max-w-[60ch] text-[1.0625rem] text-muted">
              {counts.review > 0 ? (
                <>
                  The oldest has waited <strong className="text-ink">{ago(oldest).replace(" ago", "")}</strong>
                  {hot > 0 && (
                    <>
                      {" "}
                      · <Flame className="inline size-4 text-attention-dot" aria-hidden /> {hot} hot (fit above 80)
                    </>
                  )}
                  . Approved emails land in your mailbox as drafts; nothing is sent without you.
                </>
              ) : (
                <>New drafts appear here as the engine writes them. {auto.data?.next_search ? `Next discovery ${relative(auto.data.next_search)}.` : ""}</>
              )}
            </p>
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
                  <TriangleAlert className="size-4 text-attention-dot" aria-hidden /> {counts.attention} need{counts.attention === 1 ? "s" : ""} attention
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

      {/* KPIs with the last two weeks behind them. */}
      <div data-tour="kpis" className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-4">
        <Kpi
          label="Drafts approved this week"
          value={sum(pick("approved")(thisWeek))}
          before={sum(pick("approved")(lastWeek))}
          series={pick("approved")(days)}
          why="Each approved draft is one email in your mailbox, ready to send."
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
          label="Leads added this week"
          value={sum(pick("leads")(thisWeek))}
          before={sum(pick("leads")(lastWeek))}
          series={pick("leads")(days)}
          why="Companies that became leads, by discovery or by you."
          loading={daily.isPending}
        />
        <Kpi
          label="Vendor spend this week"
          value={sum(pick("spend_micro_usd")(thisWeek))}
          before={sum(pick("spend_micro_usd")(lastWeek))}
          format={(n) => usd(n, 2)}
          series={pick("spend_micro_usd")(days)}
          invert
          why="What finders, verifiers, search and the model cost, from the call ledger."
          tone="attention"
          loading={daily.isPending}
        />
      </div>

      <SectionGroup storageKey="today">
        <NeedsYou status={status} />
        <Pipeline status={status} />
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
  no_credits: "No discovery credits left this period.",
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
  const held = Object.entries(status?.held ?? {}).filter(([, n]) => n > 0);
  const failed = status?.by_status?.failed ?? 0;
  const credit = Object.values(usage.data?.waiting_leads ?? {}).reduce((a, b) => a + b, 0) + (usage.data?.waiting_rows ?? 0);
  const sites = waitingRows.data?.length ?? 0;
  const items = [
    ...(failed ? [{ key: "failed", tone: "error" as const, label: "Failed", text: `${failed} lead${failed === 1 ? "" : "s"} stopped at a step. Most need one click to retry.`, to: "/attention" }] : []),
    ...held.map(([reason, n]) => ({ key: reason, tone: "attention" as const, label: describeHold(reason).label, text: `${n} lead${n === 1 ? "" : "s"}. ${describeHold(reason).why || "Waiting for your decision."}`, to: "/attention" })),
    ...(sites ? [{ key: "sites", tone: "attention" as const, label: "Websites to confirm", text: `${sites} uploaded row${sites === 1 ? "" : "s"} need${sites === 1 ? "s" : ""} a website before research.`, to: "/attention" }] : []),
    ...(credit ? [{ key: "credit", tone: "attention" as const, label: "Waiting for credits", text: `${credit} lead${credit === 1 ? "" : "s"} paused until credits renew or more are granted.`, to: "/attention" }] : []),
  ];
  const total = failed + held.reduce((a, [, n]) => a + n, 0) + sites + credit;
  return (
    <Section
      id="needs"
      tour="needs-you"
      tone={items.length ? "attention" : undefined}
      icon={<TriangleAlert className="size-5" />}
      title="Needs you"
      summary={items.length ? items.map((i) => i.label).join(" · ") : "Nothing is waiting on you."}
      chip={items.length ? <Chip tone="attention">{total} waiting</Chip> : <Chip tone="good">All clear</Chip>}
    >
      {items.length === 0 ? (
        <Empty art={<CheckCircle2 className="size-10 text-good-dot" />} title="All clear ✨">
          No holds, failures or credit waits. New ones show up here the moment they happen.
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

function Pipeline({ status }: { status?: Schemas["StatusOut"] }) {
  const by = status?.by_status ?? {};
  const counts = STAGES.map((s) => by[s] ?? 0);
  const total = sum(counts);
  const max = Math.max(1, ...counts);
  const stopped = (by.disqualified ?? 0) + (by.rejected ?? 0) + (by.suppressed ?? 0) + (by.failed ?? 0) + (by.held ?? 0) + (by.completed ?? 0);
  return (
    <Section
      id="pipeline"
      tour="pipeline"
      icon={<Inbox className="size-5" />}
      title="Lead pipeline"
      summary={`${total} moving · ${by.copy_ready ?? 0} waiting for review · ${by.approved ?? 0} approved`}
      chip={<Chip tone="primary">{total + stopped} leads</Chip>}
    >
      {/* A river: each band's height is how many leads sit at that stage. */}
      <div className="overflow-x-auto">
        <div className="flex min-w-[720px] items-end gap-1.5">
          {STAGES.map((stage, i) => {
            const n = counts[i]!;
            const h = 28 + (n / max) * 120;
            return (
              <Link key={stage} to="/leads" search={{ status: stage }} className="group flex flex-1 flex-col items-center gap-2" title={`${leadStatus[stage]?.label}: ${n}`}>
                <span className="tnum text-heading font-semibold text-ink">{n}</span>
                <span
                  className="w-full rounded-xl transition-[height,filter] duration-700 group-hover:brightness-110"
                  style={{ height: h, background: `linear-gradient(180deg, ${STAGE_COLOR[stage]}, color-mix(in oklab, ${STAGE_COLOR[stage]} 55%, transparent))` }}
                />
                <span className={cx("text-center text-label font-semibold", stage === "copy_ready" ? "text-attention" : "text-muted")}>{stage === "copy_ready" ? "Waiting review" : leadStatus[stage]?.label}</span>
              </Link>
            );
          })}
        </div>
      </div>
      <p className="mt-4 text-small text-muted">
        Plus {stopped} stopped (disqualified, rejected, suppressed, held, failed or completed). Click a stage to see its leads.
      </p>
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
