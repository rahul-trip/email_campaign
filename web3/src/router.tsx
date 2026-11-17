import { createRootRoute, createRoute, createRouter, lazyRouteComponent, Outlet, redirect } from "@tanstack/react-router";
import { Shell } from "./app/Shell";
import { TodayPage } from "./pages/Today";

export const SETTINGS_TABS = ["setup", "profile", "mailboxes", "limits", "plan", "team", "integrations", "account"] as const;
export type SettingsTab = (typeof SETTINGS_TABS)[number];
export type LeadsSearch = { q?: string; status?: string; hold?: string; page?: number; view?: string; sort?: string; source?: string; country?: string; fit?: number };

const root = createRootRoute({
  notFoundComponent: () => (
    <div className="card mx-auto mt-10 max-w-lg p-8 text-center">
      <div className="text-heading font-semibold text-ink">This page does not exist</div>
      <p className="mt-1 text-body text-muted">The address may be old or mistyped. Use the menu, or press ⌘K to find what you need.</p>
    </div>
  ),
  component: () => (
    <Shell>
      <Outlet />
    </Shell>
  ),
});

type Component = Parameters<typeof createRoute>[0]["component"];
const page = <P extends string>(path: P, component: Component) => createRoute({ getParentRoute: () => root, path, component });
const lazy = (load: () => Promise<Record<string, unknown>>, name: string) => lazyRouteComponent(load as () => Promise<Record<string, () => React.JSX.Element>>, name);
const text = (value: unknown): string | undefined => (typeof value === "string" && value.trim() ? value : undefined);

// The same paths as web2, so every bookmark, notification and emailed link keeps working.
const leads = createRoute({
  getParentRoute: () => root,
  path: "/leads",
  component: lazy(() => import("./pages/Leads"), "LeadsPage"),
  validateSearch: (s: Record<string, unknown>): LeadsSearch => ({
    q: text(s.q),
    status: text(s.status),
    hold: text(s.hold),
    view: text(s.view),
    sort: text(s.sort),
    source: text(s.source),
    country: text(s.country),
    fit: Number(s.fit) > 0 ? Math.min(100, Math.floor(Number(s.fit))) : undefined,
    page: Number(s.page) > 1 ? Math.floor(Number(s.page)) : undefined,
  }),
});
const review = createRoute({
  getParentRoute: () => root,
  path: "/review",
  component: lazy(() => import("./pages/Review"), "ReviewPage"),
  validateSearch: (s: Record<string, unknown>): { message?: string } => ({ message: text(s.message) }),
});
const settings = createRoute({
  getParentRoute: () => root,
  path: "/settings",
  component: lazy(() => import("./pages/Settings"), "SettingsPage"),
  validateSearch: (s: Record<string, unknown>): { tab?: SettingsTab } => ({ tab: SETTINGS_TABS.find((t) => t === s.tab) }),
});
const lead = createRoute({
  getParentRoute: () => root,
  path: "/leads/$companyId",
  component: lazy(() => import("./pages/LeadDetail"), "LeadDetailPage"),
  validateSearch: (s: Record<string, unknown>): { tab?: "overview" | "journey" | "activity" } => ({ tab: s.tab === "journey" || s.tab === "activity" ? s.tab : undefined }),
});
// The journey is a tab on the lead page now; the old address opens it.
const journey = createRoute({
  getParentRoute: () => root,
  path: "/leads/$companyId/journey",
  beforeLoad: ({ params }) => {
    throw redirect({ to: "/leads/$companyId", params, search: { tab: "journey" } });
  },
});
const mailboxes = createRoute({
  getParentRoute: () => root,
  path: "/mailboxes",
  beforeLoad: () => {
    throw redirect({ to: "/settings", search: { tab: "mailboxes" } });
  },
});

const routeTree = root.addChildren([
  page("/", TodayPage),
  review,
  page("/attention", lazy(() => import("./pages/Attention"), "AttentionPage")),
  leads,
  lead,
  journey,
  page("/linkedin", lazy(() => import("./pages/LinkedIn"), "LinkedInPage")),
  page("/targets", lazy(() => import("./pages/Targets"), "TargetsPage")),
  page("/runs", lazy(() => import("./pages/Runs"), "RunsPage")),
  page("/runs/$runId", lazy(() => import("./pages/RunDetail"), "RunDetailPage")),
  page("/onboarding", lazy(() => import("./pages/Onboarding"), "OnboardingPage")),
  page("/campaigns", lazy(() => import("./pages/Campaigns"), "CampaignsPage")),
  mailboxes,
  page("/reports", lazy(() => import("./pages/Reports"), "ReportsPage")),
  page("/compliance", lazy(() => import("./pages/Compliance"), "CompliancePage")),
  settings,
]);

export const makeRouter = (slug: string) => createRouter({ routeTree, basepath: `/w/${encodeURIComponent(slug)}`, defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof makeRouter>;
  }
}
