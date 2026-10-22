import { Link, Outlet, createRootRoute, createRoute, createRouter, lazyRouteComponent } from "@tanstack/react-router";
import { Layout } from "./app/Layout";
import { Empty, buttonClass } from "./components/ui";
import { DashboardPage } from "./pages/Dashboard";
import type { LeadsSearch } from "./pages/Leads";

function NotFound() {
  return (
    <Empty
      title="This page does not exist"
      action={
        <Link to="/" className={buttonClass("secondary")}>
          Go to the dashboard
        </Link>
      }
    >
      The link may be old, or the lead may have been deleted.
    </Empty>
  );
}

const root = createRootRoute({
  component: () => (
    <Layout>
      <Outlet />
    </Layout>
  ),
  notFoundComponent: NotFound,
});

type Component = Parameters<typeof createRoute>[0]["component"];
const page = <P extends string>(path: P, component: Component) => createRoute({ getParentRoute: () => root, path, component });

// Pages load on demand, so the first visit fetches only the shell and the page it opens.
const lazy = (load: () => Promise<Record<string, unknown>>, name: string) => lazyRouteComponent(load as () => Promise<Record<string, () => React.JSX.Element>>, name);

const text = (value: unknown): string | undefined => (typeof value === "string" && value.trim() ? value : undefined);

// The leads list keeps its filters in the URL, so a filtered view can be bookmarked or linked.
const leads = createRoute({
  getParentRoute: () => root,
  path: "/leads",
  component: lazy(() => import("./pages/Leads"), "LeadsPage"),
  validateSearch: (search: Record<string, unknown>): LeadsSearch => ({
    q: text(search.q),
    status: text(search.status),
    hold: text(search.hold),
    page: Number(search.page) > 1 ? Math.floor(Number(search.page)) : undefined,
  }),
});

// Review can open on one email, e.g. from a lead's journey.
const review = createRoute({
  getParentRoute: () => root,
  path: "/review",
  component: lazy(() => import("./pages/Review"), "ReviewPage"),
  validateSearch: (search: Record<string, unknown>): { message?: string } => ({ message: text(search.message) }),
});

const routeTree = root.addChildren([
  page("/", DashboardPage),
  review,
  page("/attention", lazy(() => import("./pages/Attention"), "AttentionPage")),
  leads,
  page("/leads/$companyId", lazy(() => import("./pages/LeadDetail"), "LeadDetailPage")),
  page("/leads/$companyId/journey", lazy(() => import("./pages/LeadJourney"), "LeadJourneyPage")),
  page("/targets", lazy(() => import("./pages/Targets"), "TargetsPage")),
  page("/runs", lazy(() => import("./pages/Runs"), "RunsPage")),
  page("/runs/$runId", lazy(() => import("./pages/RunDetail"), "RunDetailPage")),
  page("/campaigns", lazy(() => import("./pages/Campaigns"), "CampaignsPage")),
  page("/mailboxes", lazy(() => import("./pages/Mailboxes"), "MailboxesPage")),
  page("/reports", lazy(() => import("./pages/Reports"), "ReportsPage")),
  page("/compliance", lazy(() => import("./pages/Compliance"), "CompliancePage")),
  page("/settings", lazy(() => import("./pages/Settings"), "SettingsPage")),
]);

export const router = createRouter({ routeTree, defaultPreload: "intent" });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
