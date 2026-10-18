import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "@tanstack/react-router";
import { client, ok } from "../api/client";
import { Badge, Button, Card, Problem, Table, Td, Th, statusTone, usd, when, words } from "../components/ui";

export function LeadDetailPage() {
  const { companyId } = useParams({ from: "/leads/$companyId" });
  const path = { params: { path: { company_id: companyId } } };
  const queryClient = useQueryClient();
  const lead = useQuery({ queryKey: ["lead", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}", path)) });
  const timeline = useQuery({ queryKey: ["timeline", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/timeline", path)) });
  const waterfall = useQuery({ queryKey: ["waterfall", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/waterfall", path)) });

  const refresh = () => {
    for (const key of ["lead", "timeline", "waterfall", "companies", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  const retry = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/retry", path)), onSuccess: refresh });
  const release = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/release-hold", { ...path, body: {} })),
    onSuccess: refresh,
  });
  const requalify = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/requalify", path)), onSuccess: refresh });

  if (lead.isPending) return <p className="text-sm text-muted">Loading…</p>;
  if (lead.isError) return <Problem error={lead.error} />;
  const { company, contacts, messages, notes } = lead.data;
  const fieldChanges = (timeline.data ?? []).filter((e) => e.type === "field_changed" || e.type === "field_change_ignored");

  return (
    <div className="space-y-4">
      <Card
        title={company.name ?? company.domain}
        actions={
          <div className="flex gap-2">
            {company.status === "failed" && <Button onClick={() => retry.mutate()}>Retry</Button>}
            {company.status === "held" && <Button onClick={() => release.mutate()}>Release hold</Button>}
            {company.status === "disqualified" && <Button variant="secondary" onClick={() => requalify.mutate()}>Override and qualify</Button>}
          </div>
        }
      >
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Badge tone={statusTone(company.status)}>{words(company.status)}</Badge>
          {company.hold_reason && <Badge tone="amber">{words(company.hold_reason)}</Badge>}
          <span className="text-muted">{company.domain}</span>
          {company.country_code && <Badge>{company.country_code}</Badge>}
          <span>fit {company.fit_score ?? "?"}</span>
          {company.manual_fields.length > 0 && <span className="text-muted">set by you: {company.manual_fields.join(", ")}</span>}
        </div>
        {company.last_error && <p className="mt-2 text-sm text-red-800">Last error: {company.last_error}</p>}
        <Problem error={retry.error ?? release.error ?? requalify.error} />
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="People and addresses">
          {contacts.map((contact) => (
            <div key={contact.id} className="mb-3 text-sm">
              <p className="font-medium">
                #{contact.rank} {contact.full_name ?? "(no name)"} <span className="font-normal text-muted">{contact.title}</span>
              </p>
              {contact.emails.map((email) => (
                <p key={email.id} className="ml-3">
                  {email.email ?? "(erased)"} <Badge tone={statusTone(email.status)}>{words(email.status)}</Badge>{" "}
                  <span className="text-xs text-muted">
                    {words(email.provenance)}
                    {email.found_by ? ` · found by ${email.found_by}` : ""}
                    {email.verified_by ? ` · checked by ${email.verified_by}` : ""}
                  </span>
                </p>
              ))}
            </div>
          ))}
          {contacts.length === 0 && <p className="text-sm text-muted">No people yet.</p>}
          {notes.map((note) => (
            <p key={note.id} className="mt-1 rounded bg-amber-50 p-1.5 text-sm">
              Note: {note.body}
            </p>
          ))}
        </Card>

        <Card title="Emails">
          {messages.length === 0 && <p className="text-sm text-muted">Nothing written yet.</p>}
          {messages.map((m) => (
            <details key={m.id} className="mb-2 text-sm">
              <summary className="cursor-pointer">
                Touch {m.step + 1}: {m.subject} <Badge tone={statusTone(m.state)}>{words(m.state)}</Badge>
                {m.edit_distance != null && <span className="ml-1 text-xs text-muted">edited {(m.edit_distance * 100).toFixed(0)}%</span>}
              </summary>
              <pre className="mt-2 whitespace-pre-wrap rounded bg-gray-50 p-2">{m.final_body ?? m.generated_body}</pre>
            </details>
          ))}
        </Card>
      </div>

      <Card title="Waterfall: every vendor call for this lead">
        <Table>
          <thead>
            <tr>
              <Th>When</Th>
              <Th>Provider</Th>
              <Th>Call</Th>
              <Th>Result</Th>
              <Th>Cost</Th>
            </tr>
          </thead>
          <tbody>
            {waterfall.data?.map((step, index) => (
              <tr key={index}>
                <Td>{when(step.at)}</Td>
                <Td>{step.provider}</Td>
                <Td>{step.operation}</Td>
                <Td>
                  <Badge tone={step.outcome === "cache_hit" ? "blue" : step.outcome === "error" || step.outcome === "blocked_by_cap" ? "red" : "gray"}>
                    {words(step.outcome)}
                  </Badge>
                </Td>
                <Td>{usd(step.cost_micro_usd)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>

      {fieldChanges.length > 0 && (
        <Card title="Field history: your value next to the engine's">
          <Table>
            <thead>
              <tr>
                <Th>Field</Th>
                <Th>Value</Th>
                <Th>By</Th>
                <Th>Applied</Th>
              </tr>
            </thead>
            <tbody>
              {fieldChanges.map((e, index) => (
                <tr key={index}>
                  <Td>{String(e.data.field ?? "")}</Td>
                  <Td>{JSON.stringify(e.data.new ?? e.data.attempted)}</Td>
                  <Td>{e.actor}</Td>
                  <Td>{e.data.applied === false ? "no (yours wins)" : "yes"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </Card>
      )}

      <Card title="Timeline">
        <ol className="space-y-1 text-sm">
          {timeline.data?.map((e, index) => (
            <li key={index}>
              <span className="text-xs text-muted">{when(e.at)}</span> <strong>{words(e.type)}</strong> <span className="text-muted">{e.entity_type} · {e.actor}</span>{" "}
              <span className="text-xs text-muted">{summary(e.data)}</span>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function summary(data: Record<string, unknown>): string {
  const parts = ["from", "to", "reason", "hold_reason", "error"].filter((k) => data[k]).map((k) => `${k}: ${String(data[k])}`);
  return parts.join(", ");
}
