import { Outlet, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";
import { Layout } from "./components/Layout";
import { LeadDetailPage } from "./pages/LeadDetail";
import { LeadsPage } from "./pages/Leads";
import { ReviewPage } from "./pages/Review";
import { RunsPage } from "./pages/Runs";
import { SettingsPage } from "./pages/Settings";
import { TargetsPage } from "./pages/Targets";

const root = createRootRoute({
  component: () => (
    <Layout>
      <Outlet />
    </Layout>
  ),
});

const route = <P extends string>(path: P, component: () => React.JSX.Element) =>
  createRoute({ getParentRoute: () => root, path, component });

const leadDetail = createRoute({ getParentRoute: () => root, path: "/leads/$companyId", component: LeadDetailPage });

const routeTree = root.addChildren([
  route("/", ReviewPage),
  route("/targets", TargetsPage),
  route("/leads", LeadsPage),
  leadDetail,
  route("/runs", RunsPage),
  route("/settings", SettingsPage),
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
