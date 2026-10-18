import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "@tanstack/react-router";
import { useState } from "react";
import { ApiProblem, client, ok, type Schemas } from "../api/client";
import { Badge, Button, Card, Field, Input, Problem, QueryState, SaveNote, Select, Table, Td, Th, Textarea, statusTone, usd, when, words } from "../components/ui";

type Company = Schemas["CompanyOut"];
type Contact = Schemas["ContactOut"];
type Basis = Schemas["ConsentIn"]["basis"];
const BASES: Basis[] = ["express", "conspicuous_publication", "voluntary_disclosure", "existing_relationship"];
// A held lead can only go back to one of these; the others are chosen by the engine.
const RESUME_POINTS = ["researched", "contacts_found"] as const;
type Resume = (typeof RESUME_POINTS)[number];

const linkButton = "rounded-md border border-line bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-50";

export function LeadDetailPage() {
  const { companyId } = useParams({ from: "/leads/$companyId" });
  const path = { params: { path: { company_id: companyId } } };
  const queryClient = useQueryClient();
  const lead = useQuery({ queryKey: ["lead", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}", path)) });
  const timeline = useQuery({ queryKey: ["timeline", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/timeline", path)) });
  const waterfall = useQuery({ queryKey: ["waterfall", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/waterfall", path)) });
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });

  const refresh = () => {
    for (const key of ["lead", "timeline", "waterfall", "journey", "companies", "status", "review"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  const retry = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/retry", path)), onSuccess: refresh });
  const release = useMutation({
    mutationFn: (resumeTo?: Resume) => ok(client.POST("/api/companies/{company_id}/release-hold", { ...path, body: { resume_to: resumeTo } })),
    onSuccess: refresh,
  });
  const requalify = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/requalify", path)), onSuccess: refresh });
  const suppressCompany = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/suppress", path)), onSuccess: refresh });
  const suppressPerson = useMutation({
    mutationFn: (contactId: string) => ok(client.POST("/api/contacts/{contact_id}/suppress", { params: { path: { contact_id: contactId } } })),
    onSuccess: refresh,
  });
  const useSuggestion = useMutation({
    mutationFn: async (input: { version: number; code: string }) => {
      await ok(client.PATCH("/api/companies/{company_id}", { ...path, body: { row_version: input.version, country_code: input.code } }));
      return ok(client.POST("/api/companies/{company_id}/release-hold", { ...path, body: {} }));
    },
    onSuccess: refresh,
  });
  const failure = retry.error ?? release.error ?? requalify.error ?? suppressCompany.error ?? suppressPerson.error ?? useSuggestion.error;

  return (
    <QueryState query={lead}>
      {({ company, contacts, messages, notes }) => {
        const suggestion = (company.research as { country_suggestion?: { code: string; evidence: string } | null } | null)?.country_suggestion;
        const countryBlocked = company.policy_decision?.outcome === "block";
        const changes = (timeline.data ?? []).filter((e) => e.type === "field_changed" || e.type === "field_change_ignored");
        return (
          <div className="space-y-4">
            <Card
              tour="lead-header"
              title={company.name ?? company.domain}
              actions={
                <div className="flex flex-wrap gap-2">
                  <Link to="/leads/$companyId/journey" params={{ companyId }} className={linkButton}>
                    Journey
                  </Link>
                  {company.status === "failed" && <Button onClick={() => retry.mutate()}>Retry</Button>}
                  {company.status === "disqualified" && !countryBlocked && (
                    <Button variant="secondary" onClick={() => requalify.mutate()}>
                      Override and qualify
                    </Button>
                  )}
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
              {countryBlocked && company.status === "disqualified" && (
                <p className="mt-2 rounded bg-amber-50 p-2 text-sm">
                  This country's rule blocks contact. To go ahead anyway, record a person's consent below; there is no override for a block.
                </p>
              )}

              {company.status === "held" && (
                <HoldPanel company={company} suggestion={suggestion} busy={release.isPending || useSuggestion.isPending} onRelease={(to) => release.mutate(to)} onUseSuggestion={(code) => useSuggestion.mutate({ version: company.row_version, code })} />
              )}
              <div className="mt-3">
                <Problem error={failure} />
              </div>
            </Card>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card tour="lead-people" title="People and addresses">
                {contacts.map((contact) => (
                  <Person key={contact.id} contact={contact} onChanged={refresh} onSuppress={() => suppressPerson.mutate(contact.id)} />
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

            <AddPersonPanel company={company} onAdded={refresh} />

            <EditPanel key={company.row_version} company={company} campaigns={campaigns.data ?? []} onSaved={refresh} />

            <Card title="Waterfall: every vendor call for this lead">
              <QueryState query={waterfall}>
                {(steps) => (
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
                      {steps.map((step, index) => (
                        <tr key={index}>
                          <Td>{when(step.at)}</Td>
                          <Td>{step.provider}</Td>
                          <Td>{step.operation}</Td>
                          <Td>
                            <Badge tone={step.outcome === "cache_hit" ? "blue" : step.outcome === "error" || step.outcome === "blocked_by_cap" ? "red" : "gray"}>{words(step.outcome)}</Badge>
                          </Td>
                          <Td>{usd(step.cost_micro_usd)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
              </QueryState>
            </Card>

            {changes.length > 0 && (
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
                    {changes.map((e, index) => (
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
              <QueryState query={timeline}>
                {(events) => (
                  <ol className="space-y-1 text-sm">
                    {events.map((e, index) => (
                      <li key={index}>
                        <span className="text-xs text-muted">{when(e.at)}</span> <strong>{words(e.type)}</strong>{" "}
                        <span className="text-muted">
                          {e.entity_type} · {e.actor}
                        </span>{" "}
                        <span className="text-xs text-muted">{summary(e.data)}</span>
                      </li>
                    ))}
                  </ol>
                )}
              </QueryState>
            </Card>

            <Card tour="lead-suppress" title="Do not contact">
              <p className="mb-2 text-sm text-muted">
                This adds everyone at {company.domain} to the do-not-contact list and cancels their unsent emails. It cannot be undone from here.
              </p>
              <Button
                variant="danger"
                disabled={suppressCompany.isPending}
                onClick={() => {
                  if (window.confirm(`Never contact anyone at ${company.domain} again?`)) suppressCompany.mutate();
                }}
              >
                Suppress this domain
              </Button>
            </Card>
          </div>
        );
      }}
    </QueryState>
  );
}

/** What a held lead is waiting for, and the ways to let it go on. */
function HoldPanel({
  company,
  suggestion,
  busy,
  onRelease,
  onUseSuggestion,
}: {
  company: Company;
  suggestion: { code: string; evidence: string } | null | undefined;
  busy: boolean;
  onRelease: (to?: Resume) => void;
  onUseSuggestion: (code: string) => void;
}) {
  const [resumeTo, setResumeTo] = useState<Resume>("researched");
  const needsChoice = company.hold_reason === "needs_operator";
  const needsConsent = company.hold_reason === "consent_required" || company.hold_reason === "entity_unknown";
  return (
    <div className="mt-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm">
      <p className="font-medium">Held: {company.hold_reason ? words(company.hold_reason) : ""}</p>
      {needsConsent && (
        <p className="mt-1">
          {company.country_code ? `The rule for ${company.country_code}` : "The country rule"} needs prior consent, and nobody at this company has given it.
          Releasing the hold does not give consent, so it would only be held again. Add the person who agreed to be contacted and tick that they have given consent; the lead is released for you.{" "}
          <a href="#add-person" className="font-medium text-brand underline" onClick={() => document.getElementById("add-person")?.scrollIntoView({ behavior: "smooth", block: "center" })}>
            Go to Add a person
          </a>
          . Or change the rule under Settings, Country policies.
        </p>
      )}
      {suggestion && company.hold_reason === "country_unknown" && (
        <p className="mt-1">
          The research suggests <strong>{suggestion.code}</strong> ({suggestion.evidence}), but that is not proof.{" "}
          <Button className="ml-1" disabled={busy} onClick={() => onUseSuggestion(suggestion.code)}>
            Use {suggestion.code} and release
          </Button>
        </p>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        {needsChoice && (
          <Select aria-label="Resume at" value={resumeTo} onChange={(e) => setResumeTo(e.target.value as Resume)} className="max-w-52">
            {RESUME_POINTS.map((point) => (
              <option key={point} value={point}>
                Resume at {words(point)}
              </option>
            ))}
          </Select>
        )}
        <Button variant="secondary" disabled={busy} onClick={() => onRelease(needsChoice ? resumeTo : undefined)}>
          Release hold
        </Button>
        <span className="text-xs text-muted">The stage that held it will run again on the next run.</span>
      </div>
    </div>
  );
}

function Person({ contact, onChanged, onSuppress }: { contact: Contact; onChanged: () => void; onSuppress: () => void }) {
  return (
    <div className="mb-3 text-sm">
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
      {contact.status !== "forgotten" && (
        <div className="ml-3 mt-1 flex flex-wrap items-start gap-2">
          <ConsentForm contactId={contact.id} onSaved={onChanged} />
          <Button
            variant="ghost"
            className="text-red-700"
            onClick={() => {
              if (window.confirm(`Never contact ${contact.full_name ?? "this person"} again? Their unsent emails are cancelled.`)) onSuppress();
            }}
          >
            Suppress
          </Button>
        </div>
      )}
    </div>
  );
}

function ConsentForm({ contactId, onSaved }: { contactId: string; onSaved: () => void }) {
  const [open, setOpen] = useState(false);
  const [basis, setBasis] = useState<Basis>("express");
  const [evidence, setEvidence] = useState("");
  const save = useMutation({
    mutationFn: () => ok(client.POST("/api/contacts/{contact_id}/consents", { params: { path: { contact_id: contactId } }, body: { basis, evidence } })),
    onSuccess: () => {
      setOpen(false);
      setEvidence("");
      onSaved();
    },
  });
  if (!open)
    return (
      <Button variant="ghost" onClick={() => setOpen(true)}>
        Record consent
      </Button>
    );
  return (
    <div className="w-full space-y-2 rounded-md border border-line p-2">
      <Field label="Basis">
        <Select value={basis} onChange={(e) => setBasis(e.target.value as Basis)}>
          {BASES.map((b) => (
            <option key={b} value={b}>
              {words(b)}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Evidence" hint="Where the consent came from. It is kept with the record.">
        <Textarea rows={2} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
      </Field>
      <Problem error={save.error} />
      <div className="flex gap-2">
        <Button disabled={!evidence.trim() || save.isPending} onClick={() => save.mutate()}>
          Save consent
        </Button>
        <Button variant="secondary" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

/** Edit what the operator may change. A save marks the field as yours, so the engine will not overwrite it. */
function EditPanel({ company, campaigns, onSaved }: { company: Company; campaigns: Schemas["CampaignOut"][]; onSaved: () => void }) {
  const [name, setName] = useState(company.name ?? "");
  const [country, setCountry] = useState(company.country_code ?? "");
  const [priority, setPriority] = useState(String(company.priority));
  const [campaign, setCampaign] = useState(company.campaign_id ?? "");
  const save = useMutation({
    mutationFn: () =>
      ok(
        client.PATCH("/api/companies/{company_id}", {
          params: { path: { company_id: company.id } },
          body: {
            row_version: company.row_version,
            name: name.trim() || undefined,
            country_code: country.trim() || undefined,
            priority: Number(priority),
            campaign_id: campaign || undefined,
          },
        }),
      ),
    onSuccess: onSaved,
  });
  const stale = save.error instanceof ApiProblem && save.error.status === 409;
  return (
    <Card tour="lead-edit" title="Edit this lead">
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Country (two letters)">
          <Input value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} />
        </Field>
        <Field label="Priority (1 first, 9 last)">
          <Input type="number" min={1} max={9} value={priority} onChange={(e) => setPriority(e.target.value)} />
        </Field>
        <Field label="Campaign">
          <Select value={campaign} onChange={(e) => setCampaign(e.target.value)}>
            <option value="">None</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <Button disabled={save.isPending} onClick={() => save.mutate()}>
          Save changes
        </Button>
        {stale && <span className="text-sm text-amber-800">Someone changed this lead since you opened it. Reload the page and try again.</span>}
      </div>
      {!stale && <Problem error={save.error} />}
    </Card>
  );
}

/**
 * Add someone you know to this company. Ticking that they have consented records it in the same
 * step, and on a lead held for consent it then releases the hold, so the lead carries on.
 */
function AddPersonPanel({ company, onAdded }: { company: Company; onAdded: () => void }) {
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [email, setEmail] = useState("");
  const [consented, setConsented] = useState(false);
  const [basis, setBasis] = useState<Basis>("express");
  const [evidence, setEvidence] = useState("");
  const heldForConsent = company.status === "held" && (company.hold_reason === "consent_required" || company.hold_reason === "entity_unknown");
  const add = useMutation({
    mutationFn: async () => {
      await ok(
        client.POST("/api/companies/{company_id}/people", {
          params: { path: { company_id: company.id } },
          body: {
            full_name: name,
            title: title.trim() || undefined,
            email: email.trim() || undefined,
            consent_basis: consented ? basis : undefined,
            consent_evidence: consented ? evidence : undefined,
          },
        }),
      );
      // The hold was waiting for exactly this: carry the lead on.
      if (consented && heldForConsent) await ok(client.POST("/api/companies/{company_id}/release-hold", { params: { path: { company_id: company.id } }, body: {} }));
    },
    onSuccess: () => {
      setName("");
      setTitle("");
      setEmail("");
      setEvidence("");
      setConsented(false);
      onAdded();
    },
  });
  const ready = name.trim() !== "" && (!consented || evidence.trim() !== "");
  return (
    <Card tour="lead-add-person" title="Add a person">
      <div id="add-person" className="space-y-3">
        <p className="text-sm text-muted">
          Someone you know at {company.name ?? company.domain}. They are tried first when an email is written{heldForConsent ? ", and the consent below is what this lead is waiting for" : ""}.
        </p>
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Person's name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Job title (optional)">
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <Field label="Work email (optional)" hint="Leave blank to have it looked up.">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
        </div>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" checked={consented} onChange={(e) => setConsented(e.target.checked)} />
          <span>
            <strong>This person has given consent to be contacted</strong>
            <span className="block text-xs text-muted">Only tick this if you can show where it came from.</span>
          </span>
        </label>
        {consented && (
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Basis">
              <Select value={basis} onChange={(e) => setBasis(e.target.value as Basis)}>
                {BASES.map((b) => (
                  <option key={b} value={b}>
                    {words(b)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Evidence" hint="Where the consent came from. It is kept with the record.">
              <Textarea rows={2} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
            </Field>
          </div>
        )}
        <div className="flex items-center gap-3">
          <Button disabled={!ready || add.isPending} onClick={() => add.mutate()}>
            {consented && heldForConsent ? "Add person and release the hold" : "Add person"}
          </Button>
          <SaveNote mutation={add} done={consented && heldForConsent ? "Added. The lead will carry on at the next run." : "Person added."} />
        </div>
      </div>
    </Card>
  );
}

function summary(data: Record<string, unknown>): string {
  const parts = ["from", "to", "reason", "hold_reason", "error"].filter((k) => data[k]).map((k) => `${k}: ${String(data[k])}`);
  return parts.join(", ");
}
