import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode, useEffect, useMemo } from "react";
import { createRoot } from "react-dom/client";
import { SIGNED_OUT, actIn } from "./api/client";
import { PublicApp } from "./app/Public";
import { CurrentContext, go, inWorkspace, isViewing, rememberWorkspace, useMe } from "./app/session";
import { Button, Empty } from "./components/ui";
import { applyStoredTheme } from "./lib/theme";
import { makeRouter } from "./router";
import "./styles.css";

// One client per page load. Switching workspace loads the page again, so nothing cached for one
// workspace is ever shown in another.
const queryClient: QueryClient = new QueryClient({
  defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
  // Any save may finish a setup step or use a credit, so both are read again after every one.
  mutationCache: new MutationCache({
    onSuccess: () => {
      for (const key of ["setup", "usage"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  }),
});

applyStoredTheme();

const inside = window.location.pathname.match(/^\/w\/([^/]+)/);
const signIn = () => go(`/sign-in?next=${encodeURIComponent(window.location.pathname + window.location.search)}`);

/** A workspace's pages: who is signed in, may they open this workspace, then its router. */
function WorkspaceApp({ slug }: { slug: string }) {
  const me = useMe();
  const workspace = me.data?.workspaces.find((w) => w.slug === slug);
  const router = useMemo(() => makeRouter(slug), [slug]);
  useEffect(() => {
    window.addEventListener(SIGNED_OUT, signIn);
    return () => window.removeEventListener(SIGNED_OUT, signIn);
  }, []);
  useEffect(() => {
    if (me.isError) signIn();
  }, [me.isError]);
  if (!me.data)
    return (
      <div role="status" className="flex min-h-screen items-center justify-center text-muted">
        Loading…
      </div>
    );
  if (!workspace)
    return (
      <main className="flex min-h-screen items-center justify-center px-4">
        <Empty
          title="You cannot open this workspace"
          action={
            <Button
              variant="secondary"
              onClick={() => {
                rememberWorkspace(null);
                go("/");
              }}
            >
              Go to your workspaces
            </Button>
          }
        >
          You are not a member of it, or it no longer exists. Ask one of its admins for an invitation.
        </Empty>
      </main>
    );
  actIn(workspace.id);
  if (!isViewing(workspace)) rememberWorkspace(workspace.slug);
  return (
    <CurrentContext.Provider value={{ me: me.data, workspace }}>
      <RouterProvider router={router} />
    </CurrentContext.Provider>
  );
}

// `/w/{slug}` without a trailing path still opens the dashboard.
if (inside && window.location.pathname === `/w/${inside[1]}`) window.history.replaceState(null, "", inWorkspace(decodeURIComponent(inside[1]!)));

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>{inside ? <WorkspaceApp slug={decodeURIComponent(inside[1]!)} /> : <PublicApp />}</QueryClientProvider>
  </StrictMode>,
);
