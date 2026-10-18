import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type ReactNode } from "react";
import { client, ok } from "../api/client";
import { Button, Card, Field, Input, Problem } from "./ui";

function Login({ onDone }: { onDone: () => void }) {
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: () => ok(client.POST("/api/auth/login", { body: { password } })),
    onSuccess: onDone,
  });
  return (
    <main className="mx-auto mt-24 max-w-sm px-4">
      <Card title="Sign in to Outbound">
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            login.mutate();
          }}
        >
          <Field label="Password">
            <Input type="password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <Problem error={login.error} />
          <Button type="submit" disabled={!password || login.isPending}>
            Sign in
          </Button>
        </form>
      </Card>
    </main>
  );
}

const links = [
  { to: "/", label: "Review" },
  { to: "/targets", label: "Targets" },
  { to: "/leads", label: "Leads" },
  { to: "/runs", label: "Runs" },
  { to: "/settings", label: "Settings" },
] as const;

export function Layout({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: () => ok(client.GET("/api/auth/me")) });
  const status = useQuery({
    queryKey: ["status"],
    queryFn: () => ok(client.GET("/api/status")),
    enabled: me.isSuccess,
    refetchInterval: 5000,
  });
  const logout = useMutation({
    mutationFn: () => client.POST("/api/auth/logout"),
    onSuccess: () => queryClient.clear(),
  });

  if (me.isPending) return <p className="p-6 text-sm text-muted">Loading…</p>;
  if (me.isError) return <Login onDone={() => queryClient.invalidateQueries({ queryKey: ["me"] })} />;

  const waiting = status.data?.waiting_for_review ?? 0;
  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-panel">
        <nav className="mx-auto flex max-w-7xl items-center gap-1 px-4 py-2" aria-label="Main">
          <strong className="mr-4 text-brand">Outbound</strong>
          {links.map((link) => (
            <Link
              key={link.to}
              to={link.to}
              className="rounded-md px-3 py-1.5 text-sm hover:bg-gray-100"
              activeProps={{ className: "bg-gray-100 font-semibold" }}
              activeOptions={{ exact: link.to === "/" }}
            >
              {link.label}
              {link.to === "/" && waiting > 0 && (
                <span className="ml-1.5 rounded-full bg-brand px-1.5 py-0.5 text-xs text-white">{waiting}</span>
              )}
            </Link>
          ))}
          <span className="flex-1" />
          <Button variant="ghost" onClick={() => logout.mutate()}>
            Sign out
          </Button>
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-5">{children}</main>
    </div>
  );
}
