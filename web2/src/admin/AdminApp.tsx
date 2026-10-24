/** The platform's own console (/admin): a separate shell so staff never mistake it for a
 * customer's workspace. Only platform admins and the alpha's superadmin get in. */
import { Outlet, RouterProvider, createRootRoute, createRoute, createRouter, lazyRouteComponent } from "@tanstack/react-router";
import { ArrowLeft, ClipboardList, LayoutDashboard, LogOut, Settings, ShieldCheck, SlidersHorizontal, Users, UserCog, Zap } from "lucide-react";
import { useMemo, useEffect } from "react";
import { useMutation } from "@tanstack/react-query";
import { SIGNED_OUT, actIn, client } from "../api/client";
import { go, useMe } from "../app/session";
import { Button, Empty } from "../components/ui";
import { A as Link } from "./nav";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard },
  { to: "/customers", label: "Customers", icon: Users },
  { to: "/users", label: "Users", icon: UserCog },
  { to: "/plans", label: "Plans", icon: SlidersHorizontal },
  { to: "/settings", label: "Settings", icon: Settings },
  { to: "/audit", label: "Audit log", icon: ClipboardList },
] as const;

function Layout() {
  const me = useMe();
  const signOut = useMutation({ mutationFn: () => client.POST("/api/auth/logout"), onSuccess: () => go("/sign-in") });
  const staff = me.data?.user.platform_role;
  return (
    <div className="min-h-screen">
      <div className="fixed inset-x-0 top-0 z-40">
        <div className="flex h-7 items-center justify-center gap-2 bg-attention text-[11px] font-bold uppercase tracking-widest text-white" role="status">
          <ShieldCheck size={13} aria-hidden /> Admin · Alpha
          <span className="font-normal normal-case tracking-normal opacity-90">— you are changing other companies' accounts</span>
        </div>
        <header className="flex h-12 items-center gap-3 border-b border-line bg-surface px-4">
          <Link to="/" className="flex items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-lg bg-primary text-on-primary">
              <Zap size={14} aria-hidden />
            </span>
            <span className="text-lg font-bold tracking-tight">Outbound</span>
          </Link>
          <div className="ml-auto flex items-center gap-3 text-[13px]">
            <span className="hidden text-muted sm:inline">
              {me.data?.user.email} · {staff}
            </span>
            <a href="/" className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-muted hover:bg-surface-low hover:text-ink">
              <ArrowLeft size={15} aria-hidden /> Back to app
            </a>
            <button type="button" onClick={() => signOut.mutate()} className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-muted hover:bg-surface-low hover:text-ink">
              <LogOut size={15} aria-hidden /> <span className="hidden md:inline">Sign out</span>
            </button>
          </div>
        </header>
      </div>
      <aside className="fixed bottom-0 left-0 top-[76px] hidden w-52 overflow-y-auto border-r border-line bg-surface lg:block">
        <nav aria-label="Admin" className="flex flex-col gap-0.5 px-2 py-3">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link
              key={to}
              to={to}
              activeOptions={{ exact: to === "/" }}
              className="flex items-center gap-2 rounded-lg px-3 py-1.5 text-[13px] text-muted hover:bg-surface-low hover:text-ink"
              activeProps={{ className: "bg-primary-fixed font-semibold !text-primary hover:bg-primary-fixed" }}
            >
              <Icon size={17} aria-hidden /> {label}
            </Link>
          ))}
        </nav>
      </aside>
      <nav aria-label="Admin sections" className="fixed inset-x-0 top-[76px] z-30 flex gap-1 overflow-x-auto border-b border-line bg-surface px-2 py-1 lg:hidden">
        {NAV.map(({ to, label }) => (
          <Link key={to} to={to} activeOptions={{ exact: to === "/" }} className="shrink-0 rounded-lg px-3 py-1 text-[13px] text-muted" activeProps={{ className: "bg-primary-fixed font-semibold !text-primary" }}>
            {label}
          </Link>
        ))}
      </nav>
      <main id="main" className="px-4 pb-12 pt-[124px] sm:px-6 lg:ml-52 lg:pt-[92px]">
        <div className="mx-auto max-w-[1280px]">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

const root = createRootRoute({
  component: Layout,
  notFoundComponent: () => (
    <Empty title="This admin page does not exist">
      <Link to="/" className="font-semibold text-primary underline">
        Back to the overview
      </Link>
    </Empty>
  ),
});

const lazy = (load: () => Promise<Record<string, unknown>>, name: string) => lazyRouteComponent(load as () => Promise<Record<string, () => React.JSX.Element>>, name);
const page = (path: string, component: ReturnType<typeof lazy>) => createRoute({ getParentRoute: () => root, path, component });

const tree = root.addChildren([
  page("/", lazy(() => import("./Overview"), "OverviewPage")),
  page("/customers", lazy(() => import("./Customers"), "CustomersPage")),
  page("/customers/$id", lazy(() => import("./Customer"), "CustomerPage")),
  page("/users", lazy(() => import("./Users"), "UsersPage")),
  page("/plans", lazy(() => import("./Plans"), "PlansPage")),
  page("/settings", lazy(() => import("./AdminSettings"), "AdminSettingsPage")),
  page("/audit", lazy(() => import("./Audit"), "AuditPage")),
]);

const makeRouter = () => createRouter({ routeTree: tree, basepath: "/admin", defaultPreload: "intent" });

export function AdminApp() {
  const me = useMe();
  const router = useMemo(makeRouter, []);
  actIn(null); // the console is not inside a workspace
  useEffect(() => {
    const out = () => go(`/sign-in?next=${encodeURIComponent("/admin")}`);
    window.addEventListener(SIGNED_OUT, out);
    return () => window.removeEventListener(SIGNED_OUT, out);
  }, []);
  useEffect(() => {
    if (me.isError) go(`/sign-in?next=${encodeURIComponent(window.location.pathname)}`);
  }, [me.isError]);
  if (!me.data) return <div role="status" className="flex min-h-screen items-center justify-center text-muted">Loading…</div>;
  if (!me.data.user.platform_role)
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <Empty title="This is for the platform's own team" action={<Button variant="secondary" onClick={() => go("/")}>Back to the app</Button>}>
          Your account is not platform staff.
        </Empty>
      </main>
    );
  return <RouterProvider router={router as never} />;
}
