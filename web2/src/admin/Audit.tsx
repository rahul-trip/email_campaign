import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { client, ok } from "../api/client";
import { Empty, Field, Input, PageHeader, QueryState, Select, Table, Td, Th } from "../components/ui";
import { When } from "./bits";

export function AuditPage() {
  const [action, setAction] = useState("");
  const [since, setSince] = useState("");
  const query = { action: action || undefined, since: since ? new Date(since).toISOString() : undefined, limit: 300 };
  const rows = useQuery({ queryKey: ["admin", "audit", query], queryFn: () => ok(client.GET("/api/admin/audit", { params: { query } })) });
  const csv = new URLSearchParams(Object.entries({ action, since: since ? new Date(since).toISOString() : "" }).filter(([, v]) => v)).toString();
  return (
    <>
      <PageHeader
        title="Audit log"
        subtitle="Every change an admin makes, and every time a superadmin opens a workspace."
        actions={
          <a href={`/api/admin/audit.csv${csv ? `?${csv}` : ""}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg border border-outline px-3 text-[13px] font-semibold hover:bg-surface-low">
            <Download className="size-3.5" aria-hidden /> Export CSV
          </a>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <Field label="Action">
          <Select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">All</option>
            {["credits_granted", "credits_requested", "grant_revoked", "override_set", "override_revoked", "plan_changed", "plan_saved", "access_extended", "status_changed", "work_resumed", "user_disabled", "user_enabled", "platform_role_set", "platform_settings_changed", "superadmin_viewed_workspace", "customer_created"].map((a) => (
              <option key={a} value={a}>
                {a.replaceAll("_", " ")}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Since">
          <Input type="date" value={since} onChange={(e) => setSince(e.target.value)} />
        </Field>
      </div>
      <QueryState query={rows} rows={6}>
        {(all) =>
          all.length === 0 ? (
            <Empty title="Nothing recorded for that" />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-line bg-surface">
              <Table>
                <thead>
                  <tr>
                    <Th>When</Th>
                    <Th>Who</Th>
                    <Th>Customer</Th>
                    <Th>Action</Th>
                    <Th>Note</Th>
                    <Th>Details</Th>
                  </tr>
                </thead>
                <tbody>
                  {all.map((a) => (
                    <tr key={a.id}>
                      <Td className="whitespace-nowrap"><When iso={a.at} time /></Td>
                      <Td className="text-xs">{a.actor || "—"}</Td>
                      <Td>{a.workspace || "—"}</Td>
                      <Td className="font-medium">{a.action.replaceAll("_", " ")}</Td>
                      <Td className="text-muted">{a.note}</Td>
                      <Td className="max-w-xs truncate font-mono text-[11px] text-muted">
                        <span title={JSON.stringify(a.data)}>{Object.keys(a.data).length ? JSON.stringify(a.data) : ""}</span>
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )
        }
      </QueryState>
    </>
  );
}
