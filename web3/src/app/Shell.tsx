/**
 * The signed-in frame of one workspace: sidebar with live counts, top bar with the command
 * palette, engine status, bell and account menu, and the banners that matter (read-only access,
 * credits, a stuck worker, country rules off, an unconfirmed sender profile).
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { AlertTriangle, Check, ChevronDown, Compass, Eye, KeyRound, LogOut, Menu as MenuIcon, Monitor, Moon, Plus, Search, Shield, Sun, X, Zap } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { client, ok } from "../api/client";
import { cx } from "../lib/cx";
import { ago } from "../lib/format";
import { useNeedsCampaign } from "../lib/setup";
import { useTheme, type Theme } from "../lib/theme";
import { day, nearLimit, STEP_LABEL, useUsage, waitingTotal, type Usage } from "../lib/usage";
import { Avatar, buttonClass, Kbd } from "../ui/core";
import { Menu } from "../ui/overlay";
import { Ring } from "../ui/viz";
import { TourProvider, useTour } from "../tour/Tour";
import { useSetup } from "../lib/setup";
import { NotificationBell } from "./Bell";
import { CampaignGate } from "./CampaignGate";
import { CommandPalette, useCommandPalette } from "./Palette";
import { NAV } from "./nav";
import { go, inWorkspace, isViewing, rememberWorkspace, useCurrent } from "./session";

/** A run still queued after this long means no worker is picking runs up. */
const WORKER_SILENT_MS = 45_000;
const OPEN_WITHOUT_CAMPAIGN = /(^|\/)(settings|onboarding|campaigns)(\/|$)/;
const SAYS_UNCONFIRMED = /^(\/w\/[^/]+)?(\/|\/onboarding\/?)?$/;

/** Live counts every page shares: what waits in Review, what needs a person, runs in flight. */
export function useCounts() {
  const status = useQuery({ queryKey: ["status"], queryFn: () => ok(client.GET("/api/status")), refetchInterval: 5000 });
  const waiting = useQuery({ queryKey: ["waiting"], queryFn: () => ok(client.GET("/api/targets/waiting")), refetchInterval: 15000 });
  const linkedin = useQuery({ queryKey: ["linkedin", "drafted", "count"], queryFn: () => ok(client.GET("/api/linkedin", { params: { query: { state: "drafted", limit: 1 } } })), refetchInterval: 30000 });
  const usage = useUsage();
  const held = Object.values(status.data?.held ?? {}).reduce((sum, n) => sum + n, 0);
  return {
    status,
    review: status.data?.waiting_for_review ?? 0,
    attention: held + (status.data?.by_status?.failed ?? 0) + (waiting.data?.length ?? 0) + waitingTotal(usage.data),
    linkedin: linkedin.data?.total ?? 0,
  };
}

/** The tour waits until setup is done, so it never opens on top of onboarding or the campaign gate. */
export function Shell({ children }: { children: ReactNode }) {
  const viewing = isViewing(useCurrent().workspace);
  const gated = useNeedsCampaign() && !viewing;
  const setupDone = useSetup().data?.done === true;
  return (
    <TourProvider autoStart={!gated && setupDone}>
      <Frame>{children}</Frame>
    </TourProvider>
  );
}

/** The account menu asks for the tour with an event, so it needs no import cycle. */
function TourListener() {
  const { start } = useTour();
  useEffect(() => {
    window.addEventListener("outbound:tour", start);
    return () => window.removeEventListener("outbound:tour", start);
  }, [start]);
  return null;
}

function Frame({ children }: { children: ReactNode }) {
  const current = useCurrent();
  const viewing = isViewing(current.workspace);
  const gated = useNeedsCampaign() && !viewing;
  const [menuOpen, setMenuOpen] = useState(false);
  const palette = useCommandPalette();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  useEffect(() => setMenuOpen(false), [pathname]);

  const counts = useCounts();
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => ok(client.GET("/api/runs")),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2000 : 10000),
  });
  const profile = useQuery({ queryKey: ["sender"], queryFn: () => ok(client.GET("/api/settings/sender-profile")) });
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const usage = useUsage();

  const active = runs.data?.find((r) => r.status === "running") ?? runs.data?.find((r) => r.status === "queued");
  const stuck = active?.status === "queued" && Date.now() - new Date(active.created_at).getTime() > WORKER_SILENT_MS;
  const unconfirmed = profile.isSuccess && !(profile.data as Record<string, unknown>).reviewed_at && !SAYS_UNCONFIRMED.test(pathname);
  const banners: BannerItem[] = [
    ...usageBanners(usage.data),
    ...(stuck
      ? [{ key: "stuck", tone: "error" as const, node: <>A run has waited {ago(active?.created_at)} and nothing picked it up. The worker is probably not running: start it with <code className="font-mono">uv run outbound worker</code>.</> }]
      : []),
    ...(settings.data?.country_policy_enabled === false
      ? [{ key: "rules", tone: "error" as const, node: <>Country rules are switched off for this workspace: no lead is held or blocked by its country. The do-not-contact list still applies. <Link to="/compliance" className="font-semibold underline">Switch them back on</Link>.</> }]
      : []),
    ...(unconfirmed
      ? [{ key: "unconfirmed", tone: "attention" as const, node: <>Your sender profile is not confirmed, so no emails are written yet. <Link to="/settings" className="font-semibold underline">Review and confirm it</Link>.</> }]
      : []),
  ].sort((a, b) => Number(b.tone === "error") - Number(a.tone === "error"));

  const badge = { review: counts.review, attention: counts.attention, linkedin: counts.linkedin };

  // Setup is a full-screen flow of its own, with no sidebar.
  if (/\/onboarding\/?$/.test(pathname)) return <>{children}</>;

  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>

      {menuOpen && <div className="fixed inset-0 z-30 bg-[var(--scrim)] lg:hidden" onClick={() => setMenuOpen(false)} aria-hidden />}
      <aside className={cx("fixed inset-y-0 left-0 z-40 flex w-[264px] flex-col border-r border-line bg-surface transition-transform duration-300 lg:translate-x-0", menuOpen ? "translate-x-0" : "-translate-x-full")}>
        <div className="flex items-center gap-2.5 px-5 pt-5 pb-3">
          <span className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-violet text-white shadow-2">
            <Zap className="size-5" aria-hidden />
          </span>
          <WorkspaceSwitcher />
        </div>
        <div className="px-4 pb-2">
          <button type="button" data-tour="search" onClick={palette.open} className="press flex h-10 w-full items-center gap-2 rounded-xl border border-line-strong bg-surface-2 px-3 text-body text-muted hover:text-ink">
            <Search className="size-4" aria-hidden />
            <span className="flex-1 text-left">Search or jump to…</span>
            <Kbd>⌘K</Kbd>
          </button>
        </div>
        <nav aria-label="Main" data-tour="nav" className="flex-1 space-y-5 overflow-y-auto px-3 py-3">
          {NAV.map((group) => (
            <div key={group.label}>
              <div className="px-3 pb-1.5 text-label font-semibold tracking-wider text-faint uppercase">{group.label}</div>
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const count = item.badge ? badge[item.badge] : 0;
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      activeOptions={{ exact: item.to === "/" }}
                      className="group relative flex items-center gap-3 rounded-xl px-3 py-2 text-body text-ink-2 transition-colors hover:bg-surface-2 hover:text-ink"
                      activeProps={{ className: "!bg-primary-soft font-semibold !text-primary before:absolute before:inset-y-2 before:left-0 before:w-[3px] before:rounded-full before:bg-primary" }}
                    >
                      <Icon className="size-[18px] shrink-0" aria-hidden />
                      <span className="flex-1">{item.label}</span>
                      {count > 0 && (
                        <span
                          aria-label={`${count} waiting`}
                          className={cx("tnum min-w-6 rounded-full px-1.5 text-center text-label font-bold", item.badge === "attention" ? "bg-attention-soft text-attention" : "bg-primary-soft text-primary")}
                        >
                          {count}
                        </span>
                      )}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
        <CreditsMeter usage={usage.data} />
      </aside>

      <header className="glass fixed top-0 right-0 left-0 z-20 flex h-16 items-center gap-3 border-b border-line px-4 sm:px-6 lg:left-[264px]">
        <button type="button" aria-label={menuOpen ? "Close menu" : "Open menu"} aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)} className="press rounded-xl p-2 text-muted hover:bg-surface-2 lg:hidden">
          {menuOpen ? <X className="size-5" /> : <MenuIcon className="size-5" />}
        </button>
        <EngineChip run={active} stuck={stuck} />
        <div className="ml-auto flex items-center gap-1.5">
          {!viewing && (
            <Link to="/targets" className={buttonClass("primary", "md", "max-sm:hidden")}>
              <Plus className="size-4" aria-hidden /> Add leads
            </Link>
          )}
          <NotificationBell />
          <UserMenu />
        </div>
      </header>

      <main id="main" className="px-4 pt-[88px] pb-16 sm:px-6 lg:ml-[264px] lg:px-8">
        <div className="mx-auto max-w-[1360px]">
          {viewing && <ViewingBanner name={current.workspace.name} />}
          <Banners key={pathname} items={banners} />
          {gated && !OPEN_WITHOUT_CAMPAIGN.test(pathname) ? <CampaignGate /> : children}
        </div>
      </main>
      {palette.isOpen && <CommandPalette onClose={palette.close} />}
      <TourListener />
    </div>
  );
}

// ------------------------------------------------------------------ pieces

function CreditsMeter({ usage }: { usage?: Usage }) {
  const navigate = useNavigate();
  const limited = usage?.steps.filter((s) => s.limit !== null && s.limit > 0) ?? [];
  if (!usage || limited.length === 0) return null;
  // The tightest allowance is what the operator needs to see.
  const tightest = limited.reduce((a, b) => ((a.remaining ?? 0) / (a.limit ?? 1) <= (b.remaining ?? 0) / (b.limit ?? 1) ? a : b));
  const left = (tightest.remaining ?? 0) / (tightest.limit ?? 1);
  return (
    <button
      type="button"
      data-tour="credits"
      onClick={() => void navigate({ to: "/settings", search: { tab: "plan" } })}
      className="press m-3 flex items-center gap-3 rounded-2xl border border-line bg-surface-2 p-3 text-left hover:border-line-strong"
    >
      <Ring share={left} size={44} stroke={5} tone={left < 0.2 ? "error" : left < 0.4 ? "attention" : "good"} label={`${Math.round(left * 100)}`} title={`${Math.round(left * 100)}% left`} />
      <span className="min-w-0">
        <span className="block text-small font-semibold text-ink">
          <span className="tnum">{tightest.remaining}</span> of <span className="tnum">{tightest.limit}</span> left
        </span>
        <span className="block truncate text-label text-muted">
          {STEP_LABEL[tightest.step] ?? tightest.step} · renews {day(usage.period_end)}
        </span>
      </span>
    </button>
  );
}

type BannerItem = { key: string; tone: "attention" | "error"; node: ReactNode };

function Banners({ items }: { items: BannerItem[] }) {
  const [all, setAll] = useState(false);
  if (!items.length) return null;
  return (
    <div className="mb-5 space-y-2">
      {(all ? items : items.slice(0, 1)).map((item) => (
        <div key={item.key} role="alert" className={cx("flex animate-rise items-start gap-2.5 rounded-xl border px-4 py-3 text-body", item.tone === "error" ? "border-error/25 bg-error-soft text-error" : "border-attention-dot/30 bg-attention-soft text-attention")}>
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          <div className="text-ink-2">{item.node}</div>
        </div>
      ))}
      {!all && items.length > 1 && (
        <button type="button" onClick={() => setAll(true)} className="text-small font-semibold text-primary hover:underline">
          and {items.length - 1} more
        </button>
      )}
    </div>
  );
}

function EngineChip({ run, stuck }: { run?: { status: string; created_at: string; started_at?: string | null }; stuck: boolean }) {
  if (!run)
    return (
      <span className="hidden items-center gap-2 text-small text-muted md:inline-flex">
        <span className="size-2 rounded-full bg-good-dot" aria-hidden /> Engine idle
      </span>
    );
  const running = run.status === "running";
  return (
    <Link to="/runs" className={cx("inline-flex items-center gap-2 rounded-full px-3 py-1 text-small font-semibold", stuck ? "bg-error-soft text-error" : "bg-working-soft text-working")}>
      <span className={cx("size-2 rounded-full", stuck ? "bg-error-dot" : "bg-working-dot", running && "animate-pulse-dot text-working-dot")} />
      {stuck ? "Run waiting for a worker" : running ? `Run in progress · ${ago(run.started_at)}` : "Run queued"}
    </Link>
  );
}

function ViewingBanner({ name }: { name: string }) {
  return (
    <div role="status" data-tour="viewing" className="sticky top-[76px] z-10 mb-5 flex flex-wrap items-center justify-between gap-2 rounded-xl bg-error-dot px-4 py-2.5 text-body font-semibold text-white shadow-2">
      <span className="flex items-center gap-2">
        <Eye className="size-4" aria-hidden /> Superadmin view of {name}, read-only
      </span>
      <button
        type="button"
        onClick={() => {
          rememberWorkspace(null);
          go("/");
        }}
        className="rounded-lg bg-white/20 px-2.5 py-0.5 hover:bg-white/30"
      >
        Exit
      </button>
    </div>
  );
}

function WorkspaceSwitcher() {
  const { me, workspace } = useCurrent();
  return (
    <div data-tour="workspace-switcher" className="min-w-0 flex-1">
      <Menu
        label="Switch workspace"
        align="left"
        buttonClassName="press flex w-full min-w-0 items-center gap-1 rounded-lg px-1.5 py-1 text-left hover:bg-surface-2"
        button={
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-body font-bold text-ink">Outbound</span>
              <span className="block truncate text-small text-muted">{workspace.name}</span>
            </span>
            <ChevronDown className="size-4 shrink-0 text-faint" aria-hidden />
          </>
        }
        header={<span className="text-small text-muted">Your workspaces</span>}
        items={me.workspaces.map((w) => ({
          label: (
            <span className="flex items-center gap-2">
              {w.id === workspace.id ? <Check className="size-4 text-primary" aria-hidden /> : <span className="w-4" />}
              {w.name}
            </span>
          ),
          hint: w.role ?? "view only",
          current: w.id === workspace.id,
          onSelect: () => w.id !== workspace.id && go(inWorkspace(w.slug)),
        }))}
      />
    </div>
  );
}

export const THEME_NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };

function UserMenu() {
  const { me } = useCurrent();
  const signOut = useMutation({ mutationFn: () => client.POST("/api/auth/logout"), onSuccess: () => go("/sign-in") });
  const others = useMutation({ mutationFn: () => ok(client.POST("/api/auth/logout-others")) });
  const navigate = useNavigate();
  const [theme, setTheme] = useTheme();
  const ThemeIcon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  const name = me.user.name || me.user.email;
  const line = (icon: ReactNode, text: ReactNode) => (
    <span className="flex items-center gap-2.5">
      {icon}
      {text}
    </span>
  );
  return (
    <div data-tour="user-menu">
      <Menu
        label="Your account"
        buttonClassName="press flex items-center rounded-full p-0.5 hover:bg-surface-2"
        button={<Avatar name={name} className="rounded-full" />}
        header={
          <>
            <div className="text-body font-semibold text-ink">{name}</div>
            <div className="text-small text-muted">{me.user.email}</div>
            {me.user.platform_role && <div className="mt-1 text-label font-semibold text-primary uppercase">Platform {me.user.platform_role}</div>}
            {others.isSuccess && <div className="mt-1 text-small text-muted">Signed out of {others.data.signed_out} other session(s).</div>}
          </>
        }
        items={[
          ...(me.user.platform_role ? [{ label: line(<Shield className="size-4" />, "Admin console"), onSelect: () => window.location.assign("/admin") }] : []),
          { label: line(<Compass className="size-4" />, "Take the guided tour"), onSelect: () => window.dispatchEvent(new Event("outbound:tour")) },
          { label: line(<ThemeIcon className="size-4" />, `Theme: ${{ system: "system", light: "light", dark: "dark" }[theme]}`), hint: "change", onSelect: () => setTheme(THEME_NEXT[theme]) },
          { label: line(<KeyRound className="size-4" />, "Account and password"), onSelect: () => void navigate({ to: "/settings", search: { tab: "account" } }) },
          { label: line(<LogOut className="size-4" />, "Sign out everywhere else"), onSelect: () => others.mutate() },
          { label: line(<LogOut className="size-4" />, "Sign out"), onSelect: () => signOut.mutate(), tone: "danger" },
        ]}
      />
    </div>
  );
}

const WEEK_MS = 7 * 24 * 3600 * 1000;

function usageBanners(usage?: Usage): BannerItem[] {
  if (!usage) return [];
  const ending = usage.access_until ? new Date(usage.access_until).getTime() - Date.now() : null;
  const plan = (text: string) => (
    <Link to="/settings" search={{ tab: "plan" }} className="font-semibold underline">
      {text}
    </Link>
  );
  const items: BannerItem[] = [];
  if (usage.announcement) items.push({ key: "announcement", tone: "attention", node: usage.announcement });
  if (usage.access === "read_only") items.push({ key: "read-only", tone: "error", node: <>Access to this workspace ended on {day(usage.access_until)}, so it is read-only: nothing is lost, but nothing can be added or run. {plan("Ask for an extension")}.</> });
  if (usage.access === "full" && ending !== null && ending > 0 && ending < WEEK_MS) items.push({ key: "ending", tone: "attention", node: <>Your access ends on {day(usage.access_until)}. {plan("Ask for more time")}.</> });
  if (usage.access === "full" && !usage.engine) items.push({ key: "engine", tone: "error", node: "The engine is stopped for this workspace, so nothing runs. You can still read everything. Ask the team who runs the service." });
  for (const s of nearLimit(usage)) {
    const what = (STEP_LABEL[s.step] ?? s.step).toLowerCase();
    items.push({
      key: `credit-${s.step}`,
      tone: s.out ? "error" : "attention",
      node: <>{s.out ? `No credits left for ${what}` : `${s.remaining} credit${s.remaining === 1 ? "" : "s"} left for ${what}`}; they renew on {day(usage.period_end)}. {plan("See your plan")}.</>,
    });
  }
  return items;
}
