import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { AlertTriangle, Check, ChevronDown, Compass, Eye, KeyRound, LogOut, Menu as MenuIcon, Monitor, Moon, Plus, Search, Sun, X, Zap } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { client, ok } from "../api/client";
import { Avatar, Menu, buttonClass } from "../components/ui";
import { cx } from "../lib/cx";
import { ago } from "../lib/format";
import { useTheme, type Theme } from "../lib/theme";
import { TourProvider, useTour } from "../tour/Tour";
import { NAV } from "./nav";
import { go, inWorkspace, isViewing, rememberWorkspace, useCurrent } from "./session";

/** A run still queued after this long means no worker is picking runs up. */
const WORKER_SILENT_MS = 45_000;

/** The signed-in shell of one workspace. Who is signed in is settled before it renders (main.tsx). */
export function Layout({ children }: { children: ReactNode }) {
  return (
    <TourProvider autoStart>
      <Shell>{children}</Shell>
    </TourProvider>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const current = useCurrent();
  const viewing = isViewing(current.workspace);
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  useEffect(() => setMenuOpen(false), [pathname]);

  const status = useQuery({ queryKey: ["status"], queryFn: () => ok(client.GET("/api/status")), refetchInterval: 5000 });
  const waiting = useQuery({ queryKey: ["waiting"], queryFn: () => ok(client.GET("/api/targets/waiting")), refetchInterval: 15000 });
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => ok(client.GET("/api/runs")),
    refetchInterval: (query) => (query.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2000 : 10000),
  });
  const profile = useQuery({ queryKey: ["sender"], queryFn: () => ok(client.GET("/api/settings/sender-profile")) });
  const workspace = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const rulesOff = workspace.data?.country_policy_enabled === false;

  const held = Object.values(status.data?.held ?? {}).reduce((sum, n) => sum + n, 0);
  const counts = {
    review: status.data?.waiting_for_review ?? 0,
    attention: held + (status.data?.by_status?.failed ?? 0) + (waiting.data?.length ?? 0),
  };
  const active = runs.data?.find((r) => r.status === "running") ?? runs.data?.find((r) => r.status === "queued");
  const stuck = active?.status === "queued" && Date.now() - new Date(active.created_at).getTime() > WORKER_SILENT_MS;
  const unconfirmed = profile.isSuccess && !(profile.data as Record<string, unknown>).reviewed_at;

  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-2 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="fixed inset-x-0 top-0 z-40 flex h-14 items-center gap-3 border-b border-line bg-surface px-3 sm:px-4">
        <button type="button" aria-label={menuOpen ? "Close menu" : "Open menu"} aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)} className="rounded-lg p-1.5 text-muted hover:bg-surface-low lg:hidden">
          {menuOpen ? <X size={20} /> : <MenuIcon size={20} />}
        </button>
        <Link to="/" className="flex shrink-0 items-center gap-2">
          <span className="flex size-6 items-center justify-center rounded-lg bg-primary text-on-primary">
            <Zap size={14} aria-hidden />
          </span>
          <span className="text-lg font-bold tracking-tight">Outbound</span>
        </Link>
        <span className="hidden text-outline md:inline">/</span>
        <WorkspaceSwitcher />
        <SearchBox />
        <div className="ml-auto flex items-center gap-2">
          <EngineChip run={active} stuck={stuck} />
          {!viewing && (
            <Link to="/targets" className={buttonClass("primary", "md", "hidden sm:inline-flex")}>
              <Plus size={16} aria-hidden /> Add target
            </Link>
          )}
          <TourButton />
          <ThemeSwitch />
          <UserMenu />
        </div>
      </header>

      {menuOpen && <div className="fixed inset-0 top-14 z-20 bg-black/30 lg:hidden" onClick={() => setMenuOpen(false)} />}
      <aside className={cx("fixed bottom-0 left-0 top-14 z-30 w-60 overflow-y-auto border-r border-line bg-surface transition-transform lg:translate-x-0", menuOpen ? "translate-x-0" : "-translate-x-full")}>
        <nav aria-label="Main" data-tour="nav" className="flex flex-col gap-4 px-2 py-3">
          {NAV.map((group) => (
            <div key={group.label} className="flex flex-col gap-0.5">
              <div className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{group.label}</div>
              {group.items.map((item) => {
                const Icon = item.icon;
                const count = item.badge ? counts[item.badge] : 0;
                if (item.soon)
                  return (
                    <div key={item.to} title={item.soonNote} className="flex cursor-not-allowed select-none items-center justify-between rounded-lg px-3 py-1.5 text-[13px] text-muted/60">
                      <span className="flex items-center gap-2">
                        <Icon size={18} aria-hidden />
                        {item.label}
                      </span>
                      <span className="rounded bg-surface-container px-1.5 text-[10px] font-semibold uppercase">Soon</span>
                    </div>
                  );
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    activeOptions={{ exact: item.to === "/" }}
                    className="flex items-center justify-between rounded-lg px-3 py-1.5 text-[13px] text-muted transition-colors hover:bg-surface-low hover:text-ink"
                    activeProps={{ className: "bg-primary-fixed font-semibold !text-primary hover:bg-primary-fixed" }}
                  >
                    <span className="flex items-center gap-2">
                      <Icon size={18} aria-hidden />
                      {item.label}
                    </span>
                    {count > 0 && (
                      <span
                        aria-label={`${count} waiting`}
                        className={cx("rounded-full px-1.5 font-mono text-[11px] font-semibold", item.badge === "review" ? "bg-attention-container text-on-attention-container" : "bg-error-container text-on-error-container")}
                      >
                        {count}
                      </span>
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
      </aside>

      <main id="main" className="px-4 pb-12 pt-[72px] sm:px-6 lg:ml-60">
        <div className="mx-auto max-w-[1440px]">
          {viewing && <ViewingBanner name={current.workspace.name} />}
          {stuck && (
            <Banner tone="error">
              A run has been waiting {ago(active?.created_at)} and nothing has picked it up. The worker is probably not running: start it with <code className="font-mono">uv run outbound worker</code>.
            </Banner>
          )}
          {rulesOff && (
            <Banner tone="error">
              Country rules are switched off for this workspace: no lead is held or blocked by its country. The do-not-contact list still applies.{" "}
              <Link to="/compliance" className="font-semibold underline">
                Switch them back on
              </Link>
              .
            </Banner>
          )}
          {unconfirmed && (
            <Banner tone="attention">
              Your sender profile is not confirmed, so no emails are written yet.{" "}
              <Link to="/settings" className="font-semibold underline">
                Review and confirm it
              </Link>
              .
            </Banner>
          )}
          {children}
        </div>
      </main>
    </div>
  );
}

function Banner({ tone, children }: { tone: "attention" | "error"; children: ReactNode }) {
  return (
    <div role="alert" className={cx("mb-4 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-[13px]", tone === "error" ? "border-error/30 bg-error-container text-on-error-container" : "border-attention/40 bg-attention-container text-on-attention-container")}>
      <AlertTriangle size={16} className="mt-0.5 shrink-0" aria-hidden />
      <div>{children}</div>
    </div>
  );
}

/** Search for a lead from anywhere. Ctrl+K (Cmd+K) focuses it; Enter opens the filtered list. */
function SearchBox() {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        input.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <form
      role="search"
      data-tour="search"
      className="relative hidden max-w-[460px] flex-1 md:block"
      onSubmit={(event) => {
        event.preventDefault();
        void navigate({ to: "/leads", search: { q: text.trim() || undefined } });
        input.current?.blur();
      }}
    >
      <Search size={16} className="absolute left-3 top-2 text-muted" aria-hidden />
      <input
        ref={input}
        aria-label="Search leads"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Search leads by company or domain"
        className="h-8 w-full rounded-lg border border-outline bg-surface-low pl-9 pr-16 text-[13px] outline-none focus:border-primary-container focus:ring-2 focus:ring-primary-container/20"
      />
      <kbd className="absolute right-2 top-1.5 rounded border border-line bg-surface px-1.5 font-mono text-[10px] text-muted">Ctrl K</kbd>
    </form>
  );
}

function EngineChip({ run, stuck }: { run?: { status: string; created_at: string; started_at?: string | null }; stuck: boolean }) {
  if (!run) return null;
  const running = run.status === "running";
  return (
    <Link
      to="/runs"
      className={cx(
        "hidden items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold xl:inline-flex",
        stuck ? "bg-error-container text-on-error-container" : "bg-working-container text-on-working-container",
      )}
    >
      <span className={cx("size-1.5 rounded-full", stuck ? "bg-error" : "bg-working", running && "animate-pulse")} />
      {stuck ? "Run waiting for a worker" : running ? `Run in progress · ${ago(run.started_at)}` : "Run queued"}
    </Link>
  );
}

function TourButton() {
  const { start } = useTour();
  return (
    <button type="button" onClick={start} title="Take the guided tour" className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-[13px] text-muted hover:bg-surface-low hover:text-ink">
      <Compass size={16} aria-hidden /> <span className="hidden md:inline">Tour</span>
    </button>
  );
}

function ThemeSwitch() {
  const [theme, setTheme] = useTheme();
  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  const Icon = theme === "light" ? Sun : theme === "dark" ? Moon : Monitor;
  const label = { system: "Theme: follows the system", light: "Theme: light", dark: "Theme: dark" }[theme];
  return (
    <button type="button" title={label} aria-label={`${label}. Change theme`} onClick={() => setTheme(next[theme])} className="rounded-lg p-1.5 text-muted hover:bg-surface-low hover:text-ink">
      <Icon size={18} />
    </button>
  );
}

/** A superadmin reading a workspace they are not in. Stays in view; every write is refused. */
function ViewingBanner({ name }: { name: string }) {
  return (
    <div role="status" data-tour="viewing" className="sticky top-[60px] z-20 mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-error/40 bg-error px-3 py-2 text-[13px] font-semibold text-white shadow">
      <span className="flex items-center gap-2">
        <Eye size={16} aria-hidden /> Superadmin view of {name}, read-only
      </span>
      <button
        type="button"
        onClick={() => {
          rememberWorkspace(null);
          go("/");
        }}
        className="rounded-md bg-white/15 px-2 py-0.5 hover:bg-white/25"
      >
        Exit
      </button>
    </div>
  );
}

/** The workspace this page acts in; the others this person can open are one click away. */
function WorkspaceSwitcher() {
  const { me, workspace } = useCurrent();
  return (
    <Menu
      label="Switch workspace"
      tour="workspace-switcher"
      align="left"
      buttonClassName="flex items-center gap-1 rounded-lg px-1.5 py-1 text-[13px] font-semibold text-muted hover:bg-surface-low hover:text-ink"
      button={
        <>
          <span className="max-w-[180px] truncate">{workspace.name}</span>
          <ChevronDown size={14} aria-hidden />
        </>
      }
      header={<span className="text-muted">Workspaces</span>}
      items={me.workspaces.map((w) => ({
        label: (
          <>
            {w.id === workspace.id ? <Check size={14} aria-hidden /> : <span className="w-3.5" />}
            {w.name}
          </>
        ),
        hint: w.role ?? "view only",
        current: w.id === workspace.id,
        onSelect: () => w.id !== workspace.id && go(inWorkspace(w.slug)),
      }))}
    />
  );
}

/** Who is signed in: their account, and signing out. */
function UserMenu() {
  const { me } = useCurrent();
  const signOut = useMutation({ mutationFn: () => client.POST("/api/auth/logout"), onSuccess: () => go("/sign-in") });
  const others = useMutation({ mutationFn: () => ok(client.POST("/api/auth/logout-others")) });
  const navigate = useNavigate();
  const name = me.user.name || me.user.email;
  return (
    <Menu
      label="Your account"
      tour="user-menu"
      buttonClassName="flex items-center rounded-full p-0.5 hover:bg-surface-low"
      button={<Avatar name={name} />}
      header={
        <>
          <div className="font-semibold">{name}</div>
          <div className="text-muted">{me.user.email}</div>
          {me.user.platform_role && <div className="mt-1 text-[11px] font-semibold uppercase text-primary">Platform {me.user.platform_role}</div>}
          {others.isSuccess && <div className="mt-1 text-[11px] text-muted">Signed out of {others.data.signed_out} other session(s).</div>}
        </>
      }
      items={[
        { label: <><KeyRound size={14} aria-hidden /> Account and password</>, onSelect: () => void navigate({ to: "/settings", search: { tab: "account" } }) },
        { label: <><LogOut size={14} aria-hidden /> Sign out everywhere else</>, onSelect: () => others.mutate() },
        { label: <><LogOut size={14} aria-hidden /> Sign out</>, onSelect: () => signOut.mutate(), tone: "danger" },
      ]}
    />
  );
}
