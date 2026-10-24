import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../api/client";
import { useMe } from "../app/session";
import { Button, Confirm, Empty, Input, PageHeader, Problem, QueryState, Select, Table, Td, Th } from "../components/ui";
import { Pill, When } from "./bits";

export function UsersPage() {
  const me = useMe();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [asking, setAsking] = useState<{ id: string; email: string; to: "disable" } | null>(null);
  const users = useQuery({ queryKey: ["admin", "users", q], queryFn: () => ok(client.GET("/api/admin/users", { params: { query: { q: q || undefined } } })) });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
  const path = (id: string) => ({ params: { path: { user_id: id } } });
  const enable = useMutation({ mutationFn: (id: string) => client.POST("/api/admin/users/{user_id}/enable", path(id)), onSuccess: refresh });
  const disable = useMutation({
    mutationFn: (id: string) => client.POST("/api/admin/users/{user_id}/disable", path(id)),
    onSuccess: () => {
      setAsking(null);
      refresh();
    },
  });
  const signOut = useMutation({ mutationFn: (id: string) => ok(client.POST("/api/admin/users/{user_id}/sign-out", path(id))), onSuccess: refresh });
  const role = useMutation({
    mutationFn: (v: { id: string; role: "admin" | "superadmin" | null }) => client.PUT("/api/admin/users/{user_id}/platform-role", { ...path(v.id), body: { role: v.role } }).then((r) => (r.response.ok ? true : Promise.reject(new Error("That role change was refused: there must be at least one superadmin, and only a superadmin may change roles.")))),
    onSuccess: refresh,
  });
  const isSuper = me.data?.user.platform_role === "superadmin";
  return (
    <>
      <PageHeader title="Users" subtitle="Everyone with an account. Disabling signs them out everywhere at once." />
      <div className="mb-4 w-72">
        <Input aria-label="Search users" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name or email" className="w-full" />
      </div>
      <Problem error={enable.error ?? signOut.error ?? role.error} className="mb-3" />
      <QueryState query={users} rows={5}>
        {(all) =>
          all.length === 0 ? (
            <Empty title="No one matches" />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-line bg-surface">
              <Table>
                <thead>
                  <tr>
                    <Th>Person</Th>
                    <Th>Workspaces</Th>
                    <Th>Platform role</Th>
                    <Th>Last signed in</Th>
                    <Th>Status</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {all.map((u) => (
                    <tr key={u.id}>
                      <Td>
                        <span className="font-medium">{u.name || u.email}</span>
                        {u.name && <span className="block text-[11px] text-muted">{u.email}</span>}
                      </Td>
                      <Td className="text-xs">{u.workspaces.join(", ") || <span className="text-muted">none</span>}</Td>
                      <Td>
                        {isSuper && u.id !== me.data?.user.id ? (
                          <Select aria-label={`Platform role of ${u.email}`} value={u.platform_role ?? ""} onChange={(e) => role.mutate({ id: u.id, role: (e.target.value || null) as "admin" | "superadmin" | null })}>
                            <option value="">None</option>
                            <option value="admin">Admin</option>
                            <option value="superadmin">Superadmin</option>
                          </Select>
                        ) : (
                          (u.platform_role ?? "—")
                        )}
                      </Td>
                      <Td className="text-muted">
                        <When iso={u.last_login_at} time />
                      </Td>
                      <Td>{u.status === "active" ? <Pill tone="good">active</Pill> : <Pill tone="error">disabled</Pill>}</Td>
                      <Td className="space-x-1 text-right">
                        <Button size="sm" variant="ghost" busy={signOut.isPending && signOut.variables === u.id} onClick={() => signOut.mutate(u.id)}>
                          Sign out everywhere
                        </Button>
                        {u.status === "active" ? (
                          u.id !== me.data?.user.id && (
                            <Button size="sm" variant="danger-ghost" onClick={() => setAsking({ id: u.id, email: u.email, to: "disable" })}>
                              Disable
                            </Button>
                          )
                        ) : (
                          <Button size="sm" variant="secondary" onClick={() => enable.mutate(u.id)}>
                            Enable
                          </Button>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )
        }
      </QueryState>
      {asking && (
        <Confirm title={`Disable ${asking.email}?`} confirmLabel="Disable" busy={disable.isPending} error={disable.error} onClose={() => setAsking(null)} onConfirm={() => disable.mutate(asking.id)}>
          They are signed out everywhere now and cannot sign in until you enable the account again.
        </Confirm>
      )}
    </>
  );
}
