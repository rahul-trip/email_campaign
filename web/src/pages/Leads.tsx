import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { client, ok } from "../api/client";
import { Badge, Card, Empty, Input, Problem, Select, Table, Td, Th, statusTone, words } from "../components/ui";

const STATUSES = ["new", "researched", "qualified", "disqualified", "contacts_found", "email_ready", "held", "copy_ready", "approved", "in_sequence", "replied", "completed", "rejected", "suppressed", "failed"] as const;
const HOLDS = ["catch_all_resolving", "catch_all_unverified", "consent_required", "country_unknown", "entity_unknown", "needs_operator"] as const;
const PAGE = 25;

export function LeadsPage() {
  const [status, setStatus] = useState("");
  const [hold, setHold] = useState("");
  const [text, setText] = useState("");
  const [offset, setOffset] = useState(0);
  const leads = useQuery({
    queryKey: ["companies", status, hold, text, offset],
    queryFn: () =>
      ok(
        client.GET("/api/companies", {
          params: {
            query: {
              status: (status || undefined) as (typeof STATUSES)[number] | undefined,
              hold_reason: (hold || undefined) as (typeof HOLDS)[number] | undefined,
              q: text || undefined,
              limit: PAGE,
              offset,
            },
          },
        }),
      ),
  });
  const total = leads.data?.total ?? 0;
  const reset = (apply: () => void) => {
    apply();
    setOffset(0);
  };
  return (
    <Card tour="leads-list" title={`Leads (${total})`}>
      <div className="mb-3 flex flex-wrap gap-2">
        <Input aria-label="Search" placeholder="Search name or domain" value={text} onChange={(e) => reset(() => setText(e.target.value))} className="max-w-xs" />
        <Select aria-label="Status" value={status} onChange={(e) => reset(() => setStatus(e.target.value))} className="max-w-48">
          <option value="">Any status</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {words(s)}
            </option>
          ))}
        </Select>
        <Select aria-label="Hold reason" value={hold} onChange={(e) => reset(() => setHold(e.target.value))} className="max-w-56">
          <option value="">Any hold reason</option>
          {HOLDS.map((s) => (
            <option key={s} value={s}>
              {words(s)}
            </option>
          ))}
        </Select>
      </div>
      {leads.isPending && <p role="status" className="text-sm text-muted">Loading…</p>}
      {leads.isError && <Problem error={leads.error} />}
      {leads.data?.items.length === 0 && <Empty>No leads match.</Empty>}
      <Table>
        <thead>
          <tr>
            <Th>Company</Th>
            <Th>Status</Th>
            <Th>Country</Th>
            <Th>Fit</Th>
            <Th>Why it stopped</Th>
            <Th>
              <span className="sr-only">Journey</span>
            </Th>
          </tr>
        </thead>
        <tbody>
          {leads.data?.items.map((c, index) => (
            <tr key={c.id}>
              <Td>
                <Link to="/leads/$companyId" params={{ companyId: c.id }} className="font-medium text-brand hover:underline">
                  {c.name ?? c.domain}
                </Link>
                <span className="block text-xs text-muted">{c.domain}</span>
              </Td>
              <Td>
                <Badge tone={statusTone(c.status)}>{words(c.status)}</Badge>
              </Td>
              <Td>{c.country_code}</Td>
              <Td>{c.fit_score}</Td>
              <Td className="text-muted">{c.hold_reason ? words(c.hold_reason) : c.last_error}</Td>
              <Td>
                <Link data-tour={index === 0 ? "leads-journey" : undefined} to="/leads/$companyId/journey" params={{ companyId: c.id }} className="whitespace-nowrap text-brand hover:underline" aria-label={`Journey of ${c.name ?? c.domain}`}>
                  Journey →
                </Link>
              </Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="mt-3 flex items-center justify-between text-sm">
        <button className="disabled:opacity-40" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
          ← Newer
        </button>
        <span className="text-muted">
          {total === 0 ? 0 : offset + 1}–{Math.min(offset + PAGE, total)} of {total}
        </span>
        <button className="disabled:opacity-40" disabled={offset + PAGE >= total} onClick={() => setOffset(offset + PAGE)}>
          Older →
        </button>
      </div>
    </Card>
  );
}
