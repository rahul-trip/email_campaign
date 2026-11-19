import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { client, ok } from "../api/client";
import { Button, Checkbox, Dialog, Empty, Field, Input, PageHeader, Problem, QueryState, Select, StackTable, Td, Th } from "../ui/compat";
import { ago, credits, usd } from "../lib/format";
import { AccessPill, Pill, UseBar, type Row } from "./bits";
import { A } from "./nav";

export function CustomersPage() {
  const [q, setQ] = useState("");
  const [plan, setPlan] = useState("");
  const [access, setAccess] = useState("");
  const [near, setNear] = useState(false);
  const [waiting, setWaiting] = useState(false);
  const [mailbox, setMailbox] = useState(false);
  const [inviting, setInviting] = useState(false);
  const query = { q: q || undefined, plan: plan || undefined, access: access || undefined, near_limit: near || undefined, waiting: waiting || undefined, mailbox_problem: mailbox || undefined };
  const rows = useQuery({ queryKey: ["admin", "customers", query], queryFn: () => ok(client.GET("/api/admin/customers", { params: { query } })), refetchInterval: 30_000 });
  const plans = useQuery({ queryKey: ["admin", "plans"], queryFn: () => ok(client.GET("/api/admin/plans")) });
  return (
    <>
      <PageHeader
        title="Customers"
        subtitle="Every company on the platform. Open one to change its plan, limits, credits or access."
        actions={
          <Button onClick={() => setInviting(true)}>
            <Plus className="size-4" aria-hidden /> Invite customer
          </Button>
        }
      />
      <div className="mb-4 flex flex-wrap items-end gap-3" data-tour="admin-filters">
        <Field label="Search" className="w-64">
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or address" className="w-full" />
        </Field>
        <Field label="Plan">
          <Select value={plan} onChange={(e) => setPlan(e.target.value)}>
            <option value="">All</option>
            {plans.data?.plans.map((p) => (
              <option key={p.code} value={p.code}>
                {p.name}
              </option>
            ))}
            <option value="unlimited">Unlimited</option>
          </Select>
        </Field>
        <Field label="Access">
          <Select value={access} onChange={(e) => setAccess(e.target.value)}>
            <option value="">All</option>
            <option value="full">Open</option>
            <option value="read_only">Ended (read-only)</option>
            <option value="locked">Closed</option>
          </Select>
        </Field>
        <Checkbox label="Near a limit" checked={near} onChange={setNear} />
        <Checkbox label="Waiting for credits" checked={waiting} onChange={setWaiting} />
        <Checkbox label="Mailbox problem" checked={mailbox} onChange={setMailbox} />
      </div>
      <QueryState query={rows} rows={6} shape="table">
        {(all) =>
          all.length === 0 ? (
            <Empty title="No customer matches">Change the filters, or invite the first one.</Empty>
          ) : (
            <StackTable>
                <thead>
                  <tr>
                    <Th>Customer</Th>
                    <Th>Plan</Th>
                    <Th>Access</Th>
                    <Th>AI credits this period</Th>
                    <Th>Used this month</Th>
                    <Th>Mailboxes</Th>
                    <Th>Skips directory</Th>
                    <Th>Active</Th>
                  </tr>
                </thead>
                <tbody>
                  {all.map((row) => (
                    <CustomerLine key={row.id} row={row} />
                  ))}
                </tbody>
            </StackTable>
          )
        }
      </QueryState>
      {inviting && <InviteDialog onClose={() => setInviting(false)} />}
    </>
  );
}

function CustomerLine({ row }: { row: Row }) {
  return (
    <tr className="hover:bg-surface-2">
      <Td>
        <A to="/customers/$id" params={{ id: row.id }} className="font-semibold hover:text-primary hover:underline">
          {row.name}
        </A>
        <span className="block font-mono text-label text-muted">{row.slug}</span>
      </Td>
      <Td label="Plan">{row.plan_name}</Td>
      <Td label="Access">
        <AccessPill row={row} />
      </Td>
      <Td label="AI credits this period">
        <div className="flex items-center gap-1.5">
          <UseBar used={Math.round(row.credits.used_milli / 1000)} total={row.credits.allowance} />
          {row.waiting > 0 && <Pill tone="attention">{row.waiting} waiting</Pill>}
        </div>
      </Td>
      <Td label="Used this month" className="font-mono">
        {credits(row.credits_milli)}
        <span className="block text-label text-muted">{usd(row.cost_micro_usd)} cost</span>
      </Td>
      <Td label="Mailboxes">{row.mailboxes === 0 ? <span className="text-muted">none</span> : row.mailbox_problems ? <Pill tone="error">{row.mailbox_problems} need care</Pill> : <Pill tone="good">{row.mailboxes} ok</Pill>}</Td>
      <Td label="Skips directory">{row.features.includes("directory_bypass") ? "allowed" : "off"}</Td>
      <Td label="Active" className="text-muted">{row.last_active ? ago(row.last_active) : "never"}</Td>
    </tr>
  );
}

function InviteDialog({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [email, setEmail] = useState("");
  const invite = useMutation({
    mutationFn: () => ok(client.POST("/api/admin/customers", { body: { name: name.trim(), website: website.trim(), admin_email: email.trim() } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["admin"] }),
  });
  return (
    <Dialog
      title="Invite a customer"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            {invite.isSuccess ? "Close" : "Cancel"}
          </Button>
          {!invite.isSuccess && (
            <Button busy={invite.isPending} disabled={!name.trim() || !email.includes("@")} onClick={() => invite.mutate()}>
              Create and invite
            </Button>
          )}
        </>
      }
    >
      {invite.isSuccess ? (
        <p role="status" className="text-body">
          Created. {invite.data.invited} has an invitation by email; they set a password and start the guided setup. The new workspace is on the default plan.
        </p>
      ) : (
        <>
          <Field label="Company name">
            <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus className="w-full" />
          </Field>
          <Field label="Website" hint="Optional. Fills in their profile.">
            <Input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="company.com" className="w-full" />
          </Field>
          <Field label="First admin's email">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full" />
          </Field>
          <Problem error={invite.error} />
        </>
      )}
    </Dialog>
  );
}
