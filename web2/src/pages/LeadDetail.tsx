import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useRouterState } from "@tanstack/react-router";
import { ExternalLink, GitFork, Globe2, Mail, RefreshCw, ShieldOff, Trash2, Unlock, UserPlus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { ApiProblem, client, ok, type Schemas } from "../api/client";
import { PolicySkip } from "../components/PolicySkip";
import { SkipCheck } from "../components/SkipCheck";
import { StatusBadge } from "../components/StatusBadge";
import {
  Button,
  Callout,
  Card,
  Checkbox,
  Confirm,
  Empty,
  Field,
  Input,
  Label,
  PageHeader,
  Problem,
  QueryState,
  SaveNote,
  Select,
  Skeleton,
  Table,
  Td,
  Textarea,
  Th,
  buttonClass,
} from "../components/ui";
import { cx } from "../lib/cx";
import { ago, usd, when, words } from "../lib/format";
import { callOutcome, describe, describeHold, emailStatus, leadStatus, messageState } from "../lib/status";

type Company = Schemas["CompanyOut"];
type Contact = Schemas["ContactOut"];
type Basis = Schemas["ConsentIn"]["basis"];

const BASES: [Basis, string][] = [
  ["express", "Express consent (they agreed)"],
  ["conspicuous_publication", "Address published conspicuously"],
  ["voluntary_disclosure", "They gave you the address"],
  ["existing_relationship", "Existing business relationship"],
];
// A lead held for the operator's decision can resume at one of these.
const RESUME_POINTS = ["researched", "contacts_found"] as const;
type Resume = (typeof RESUME_POINTS)[number];

function useRefreshLead() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ["lead", "timeline", "waterfall", "journey", "companies", "status", "review"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
}

export function LeadDetailPage() {
  const { companyId } = useParams({ from: "/leads/$companyId" });
  const path = { params: { path: { company_id: companyId } } };
  const refresh = useRefreshLead();
  const lead = useQuery({ queryKey: ["lead", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}", path)) });
  const timeline = useQuery({ queryKey: ["timeline", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/timeline", path)) });
  const waterfall = useQuery({ queryKey: ["waterfall", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/waterfall", path)) });
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });

  const retry = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/retry", path)), onSuccess: refresh });
  const requalify = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/requalify", path)), onSuccess: refresh });

  // Links such as "Add a person with consent" point at a section of this page.
  const hash = useRouterState({ select: (state) => state.location.hash });
  useEffect(() => {
    if (hash && lead.isSuccess) document.getElementById(hash)?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [hash, lead.isSuccess]);

  if (lead.isPending) return <Skeleton rows={8} />;
  if (lead.isError)
    return (
      <Card>
        <Problem error={lead.error} />
        <Link to="/leads" className={cx(buttonClass("secondary", "sm"), "mt-3")}>
          Back to leads
        </Link>
      </Card>
    );

  const { company, contacts, messages, notes } = lead.data;
  const hold = company.hold_reason ? describeHold(company.hold_reason) : null;
  const countryBlocked = (company.policy_decision as { outcome?: string } | null)?.outcome === "block";
  // Only the times the engine tried to overwrite a value you set: yours was kept, theirs is shown.
  const changes = (timeline.data ?? []).filter((e) => e.type === "field_changed" && e.data.applied === false);
  const emailStepFailed = company.status === "failed" && company.failed_stage === "email";
  // The person the email waiting for review (or approved) is written to.
  const liveRecipient = messages.find((m) => m.state === "generated" || m.state === "approved")?.contact_id;

  return (
    <>
      <PageHeader
        crumbs={
          <>
            <Link to="/leads" className="hover:text-ink hover:underline">
              Leads
            </Link>{" "}
            / <span className="text-ink">{company.name ?? company.domain}</span>
          </>
        }
        title={company.name ?? company.domain}
        subtitle={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <a href={`https://${company.domain}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-xs hover:text-primary">
              {company.domain} <ExternalLink className="size-3" aria-hidden />
            </a>
            <span className="text-xs">Country {company.country_code ?? "unknown"}</span>
            <span className="text-xs">Fit {company.fit_score ?? "?"}/100</span>
            <span className="text-xs">Priority {company.priority}</span>
            <span className="text-xs">Added {ago(company.created_at)}</span>
          </span>
        }
        actions={
          <>
            <Link to="/leads/$companyId/journey" params={{ companyId }} className={buttonClass("secondary")}>
              <GitFork className="size-3.5" aria-hidden /> Journey
            </Link>
            {company.status === "failed" && (
              <Button busy={retry.isPending} onClick={() => retry.mutate()}>
                <RefreshCw className="size-3.5" aria-hidden /> Retry
              </Button>
            )}
            {company.status === "disqualified" && !countryBlocked && (
              <Button variant="secondary" busy={requalify.isPending} onClick={() => requalify.mutate()}>
                Override and qualify
              </Button>
            )}
          </>
        }
      />

      <div data-tour="lead-header" className="mb-5 flex flex-wrap items-center gap-2">
        <StatusBadge status={describe(leadStatus, company.status)} />
        {hold && <span className="rounded-full bg-attention-container px-2 py-0.5 text-xs font-medium text-on-attention-container">{hold.label}</span>}
        <span className="rounded-full bg-surface-container px-2 py-0.5 text-xs">company type: {words(company.legal_entity_type)}</span>
        {company.manual_fields.length > 0 && <span className="text-xs text-muted">Set by you, kept as you set it: {company.manual_fields.map(words).join(", ")}</span>}
      </div>

      <div className="mb-5 space-y-3">
        <Problem error={retry.error ?? requalify.error} />
        {company.status === "failed" && (
          <Callout tone="error" title={`The ${company.failed_stage ? words(company.failed_stage) : ""} step failed`}>
            {company.last_error}
            {emailStepFailed &&
              " Edit a person below to complete their name or give their work email, and the step is retried. If you know an address works even though the check could not prove it, press Skip the check next to it."}
          </Callout>
        )}
        {company.status === "disqualified" && countryBlocked && (
          <Callout tone="attention" title="This country's rule blocks contact">
            To go ahead, add a person who has given consent, skip the country rule for this lead under <em>Country rule</em>, or change the rule under Policies and privacy.
          </Callout>
        )}
        {company.status === "disqualified" && !countryBlocked && company.fit_reason && (
          <Callout tone="info" title="Fit too low for the campaign">
            {company.fit_reason}
          </Callout>
        )}
        {company.status === "held" && <HoldPanel company={company} onDone={refresh} />}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-5">
          <Card tour="lead-people" title={`People and addresses (${contacts.length})`} subtitle="In rank order: the first usable person gets the email.">
            {contacts.length === 0 ? (
              <Empty title="No people yet">Research finds people on the company's site; or add someone you know below.</Empty>
            ) : (
              <ul className="divide-y divide-line">
                {contacts.map((contact) => (
                  <Person
                    key={contact.id}
                    contact={contact}
                    onChanged={refresh}
                    retryAfterEdit={emailStepFailed}
                    company={company}
                    recipient={liveRecipient === contact.id}
                    writtenTo={messages.some((m) => m.contact_id === contact.id)}
                  />
                ))}
              </ul>
            )}
          </Card>

          <AddPerson company={company} onAdded={refresh} />

          <Card title={`Emails (${messages.length})`}>
            {messages.length === 0 ? (
              <p className="text-xs text-muted">Nothing written yet.</p>
            ) : (
              <div className="space-y-2">
                {messages.map((m) => (
                  <details key={m.id} className="group rounded-lg border border-line">
                    <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-3 py-2.5 hover:bg-surface-low">
                      <span className="font-mono text-xs font-semibold">Email {m.step + 1}</span>
                      <span className="min-w-0 flex-1 truncate text-[13px]">{m.subject}</span>
                      <StatusBadge status={describe(messageState, m.state)} />
                      {m.edit_distance != null && <span className="text-[11px] text-muted">edited {Math.round(m.edit_distance * 100)}%</span>}
                      {m.sent_at && <span className="text-[11px] text-muted">sent {ago(m.sent_at)}</span>}
                    </summary>
                    <pre className="whitespace-pre-wrap border-t border-line bg-surface-low p-3 font-sans text-[13px] leading-relaxed">{m.final_body ?? m.generated_body}</pre>
                  </details>
                ))}
              </div>
            )}
          </Card>

          <Research company={company} />

          <Card title="Vendor calls" subtitle="Every paid call made for this lead, in order. A cache hit reused a stored answer at no cost.">
            <QueryState query={waterfall}>
              {(steps) =>
                steps.length === 0 ? (
                  <p className="text-xs text-muted">No vendor calls yet.</p>
                ) : (
                  <Table>
                    <thead>
                      <tr>
                        <Th>When</Th>
                        <Th>Vendor</Th>
                        <Th>Call</Th>
                        <Th>Result</Th>
                        <Th className="text-right">Cost</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {steps.map((step, i) => (
                        <tr key={i}>
                          <Td className="whitespace-nowrap text-xs text-muted">{when(step.at)}</Td>
                          <Td className="font-medium">{step.provider}</Td>
                          <Td className="text-xs">{words(step.operation)}</Td>
                          <Td>
                            <StatusBadge status={describe(callOutcome, step.outcome)} />
                          </Td>
                          <Td className="text-right font-mono text-xs">{usd(step.cost_micro_usd)}</Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )
              }
            </QueryState>
          </Card>

          {changes.length > 0 && (
            <Card title="Your values kept" subtitle="The engine found a different value for something you set. Yours was kept; this is what it found.">
              <Table>
                <thead>
                  <tr>
                    <Th>Field</Th>
                    <Th>Engine's value, not applied</Th>
                    <Th>When</Th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((e, i) => (
                    <tr key={i}>
                      <Td>{words(String(e.data.field ?? ""))}</Td>
                      <Td className="max-w-md truncate font-mono text-xs">{JSON.stringify(e.data.new ?? e.data.attempted)}</Td>
                      <Td className="whitespace-nowrap text-xs text-muted">{when(e.at)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </Card>
          )}

          <Card title="Timeline">
            <QueryState query={timeline}>
              {(events) => (
                <ol className="relative space-y-3 border-l border-line pl-4">
                  {events.map((e, i) => (
                    <li key={i} className="relative">
                      <span className={cx("absolute -left-[21px] top-1 size-2.5 rounded-full border-2 border-surface", e.actor === "operator" ? "bg-primary-container" : "bg-outline")} aria-hidden />
                      <div className="text-[13px]">
                        <span className="font-medium">{words(e.type)}</span> <span className="text-xs text-muted">{e.actor === "operator" ? "by you" : `by ${e.actor}`}</span>
                      </div>
                      <div className="text-xs text-muted">
                        {when(e.at)}
                        {summary(e.data) && ` · ${summary(e.data)}`}
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </QueryState>
          </Card>
        </div>

        <div className="flex flex-col gap-5">
          <Card tour="lead-policy" title="Country rule" subtitle={`Rule for ${company.country_code ?? "an unknown country"}. You can skip it for this lead.`}>
            <PolicySkip key={`${company.row_version}`} company={company} heldAt={lead.data.held_at} />
          </Card>
          <EditLead key={company.row_version} company={company} campaigns={campaigns.data ?? []} onSaved={refresh} />
          {notes.length > 0 && (
            <Card title="Notes">
              <ul className="space-y-2">
                {notes.map((note) => (
                  <li key={note.id} className="rounded-lg bg-surface-low p-2.5 text-[13px]">
                    {note.body}
                    <div className="mt-1 text-[11px] text-muted">
                      {words(note.source)}
                      {note.created_at && ` · ${ago(note.created_at)}`}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          <DangerZone company={company} />
        </div>
      </div>
    </>
  );
}

/** What a held lead is waiting for, and the ways to let it carry on. */
function HoldPanel({ company, onDone }: { company: Company; onDone: () => void }) {
  const hold = describeHold(company.hold_reason ?? "");
  const [resumeTo, setResumeTo] = useState<Resume>("researched");
  const path = { params: { path: { company_id: company.id } } };
  const suggestion = (company.research as { country_suggestion?: { code: string; evidence: string } | null } | null)?.country_suggestion;
  const release = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/release-hold", { ...path, body: { resume_to: company.hold_reason === "needs_operator" ? resumeTo : undefined } })),
    onSuccess: onDone,
  });
  const setCountry = useMutation({
    mutationFn: async (code: string) => {
      await ok(client.PATCH("/api/companies/{company_id}", { ...path, body: { row_version: company.row_version, country_code: code } }));
      return ok(client.POST("/api/companies/{company_id}/release-hold", { ...path, body: {} }));
    },
    onSuccess: onDone,
  });
  return (
    <Card tone="attention" title={<span className="text-on-attention-container">Held: {hold.label}</span>}>
      <p className="text-[13px]">{hold.why}</p>
      <p className="mt-1 text-[13px] font-medium">{hold.fix}</p>
      {hold.action === "person" && (
        <p className="mt-1 text-xs text-muted">Releasing the hold does not give consent, so it would only be held again. Consent belongs to a person and is recorded with them.</p>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {hold.action === "country" && suggestion && (
          <Button busy={setCountry.isPending} onClick={() => setCountry.mutate(suggestion.code)}>
            <Globe2 className="size-3.5" aria-hidden /> Use {suggestion.code} and release
          </Button>
        )}
        {hold.action === "person" && (
          <a href="#add-person" className={buttonClass("primary")} onClick={(e) => (e.preventDefault(), document.getElementById("add-person")?.scrollIntoView({ behavior: "smooth", block: "start" }))}>
            <UserPlus className="size-3.5" aria-hidden /> Add a person with consent
          </a>
        )}
        {company.hold_reason === "needs_operator" && (
          <Select aria-label="Resume at" value={resumeTo} onChange={(e) => setResumeTo(e.target.value as Resume)} className="w-auto">
            {RESUME_POINTS.map((point) => (
              <option key={point} value={point}>
                Resume at {describe(leadStatus, point).label.toLowerCase()}
              </option>
            ))}
          </Select>
        )}
        {hold.action !== "wait" && (
          <Button variant="secondary" busy={release.isPending} onClick={() => release.mutate()}>
            <Unlock className="size-3.5" aria-hidden /> Release hold
          </Button>
        )}
      </div>
      {suggestion && hold.action === "country" && <p className="mt-2 text-xs text-muted">Suggested from the research: {suggestion.evidence}. It is a suggestion, not proof.</p>}
      <p className="mt-2 text-[11px] text-muted">
        The stage that held it runs again on the next run. A country-rule hold is refused while nothing has changed; you can also skip the country rule for this lead under <em>Country rule</em>.
      </p>
      <Problem error={release.error ?? setCountry.error} className="mt-2" />
    </Card>
  );
}

// A lead in one of these can be pointed at a different person before the email reaches the mailbox.
const RECIPIENT_CHANGEABLE = new Set(["contacts_found", "email_ready", "copy_ready", "approved", "failed", "held"]);
const WORKABLE = new Set(["candidate", "active"]);

function Person({
  contact,
  onChanged,
  retryAfterEdit,
  company,
  recipient,
  writtenTo,
}: {
  contact: Contact;
  onChanged: () => void;
  retryAfterEdit: boolean;
  company: Company;
  recipient: boolean;
  writtenTo: boolean;
}) {
  const companyId = company.id;
  const [panel, setPanel] = useState<"edit" | "consent" | null>(null);
  const [suppressing, setSuppressing] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const remove = useMutation({
    mutationFn: () => ok(client.DELETE("/api/contacts/{contact_id}", { params: { path: { contact_id: contact.id } } })),
    onSuccess: () => {
      setRemoving(false);
      onChanged();
    },
  });
  const confirm = useMutation({
    mutationFn: () => ok(client.POST("/api/contacts/{contact_id}/confirm", { params: { path: { contact_id: contact.id } } })),
    onSuccess: onChanged,
  });
  const unconfirmed = contact.status === "unconfirmed";
  const choose = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/change-recipient", { params: { path: { company_id: companyId } }, body: { contact_id: contact.id } })),
    onSuccess: () => {
      setChoosing(false);
      onChanged();
    },
  });
  const canChoose = !recipient && WORKABLE.has(contact.status) && RECIPIENT_CHANGEABLE.has(company.status);
  const suppress = useMutation({
    mutationFn: () => ok(client.POST("/api/contacts/{contact_id}/suppress", { params: { path: { contact_id: contact.id } } })),
    onSuccess: () => {
      setSuppressing(false);
      onChanged();
    },
  });
  const gone = contact.status === "forgotten";
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-full bg-primary-fixed font-mono text-[11px] font-semibold text-primary">{contact.rank}</span>
            <span className="font-semibold">{contact.full_name ?? "(no name)"}</span>
            {contact.title && <span className="text-xs text-muted">{contact.title}</span>}
            {unconfirmed && (
              <span className="rounded-full bg-attention-container px-2 py-0.5 text-[11px] font-medium text-on-attention-container" title="A search found this person, but their profile does not clearly say they work here.">
                Unconfirmed: check they work here
              </span>
            )}
            {!unconfirmed && contact.status !== "active" && contact.status !== "candidate" && <span className="rounded bg-surface-container px-1.5 text-[11px]">{words(contact.status)}</span>}
            {recipient && <span className="rounded-full bg-primary-fixed px-2 py-0.5 text-[11px] font-medium text-primary">The email is to this person</span>}
            {contact.linkedin_url && (
              <a href={contact.linkedin_url} target="_blank" rel="noreferrer" className="text-[11px] text-primary hover:underline">
                LinkedIn
              </a>
            )}
          </div>
          <ul className="mt-1.5 space-y-1 pl-8">
            {contact.emails.map((email) => (
              <li key={email.id} className="flex flex-wrap items-center gap-2 text-xs">
                <Mail className="size-3.5 text-muted" aria-hidden />
                <span className="font-mono">{email.email ?? "(erased)"}</span>
                <StatusBadge status={describe(emailStatus, email.status)} />
                <span className="text-muted">
                  {words(email.provenance)}
                  {email.found_by && ` · found by ${email.found_by}`}
                  {email.verified_by && ` · checked by ${email.verified_by}`}
                </span>
                {!gone && WORKABLE.has(contact.status) && <SkipCheck email={email} personName={contact.full_name} />}
              </li>
            ))}
            {contact.emails.length === 0 && <li className="text-xs text-muted">No address yet.</li>}
          </ul>
        </div>
        {!gone && (
          <div className="flex flex-wrap gap-1">
            {unconfirmed && (
              <Button size="sm" busy={confirm.isPending} onClick={() => confirm.mutate()}>
                Confirm they work here
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={() => setPanel(panel === "edit" ? null : "edit")}>
              Edit
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setPanel(panel === "consent" ? null : "consent")}>
              Record consent
            </Button>
            {canChoose && (
              <Button variant="ghost" size="sm" onClick={() => setChoosing(true)}>
                Write to this person instead
              </Button>
            )}
            {!writtenTo && (
              <Button variant="danger-ghost" size="sm" onClick={() => setRemoving(true)}>
                Remove
              </Button>
            )}
            <Button variant="danger-ghost" size="sm" onClick={() => setSuppressing(true)}>
              Suppress
            </Button>
          </div>
        )}
      </div>
      {panel === "edit" && (
        <EditPerson
          contact={contact}
          retry={retryAfterEdit ? () => ok(client.POST("/api/companies/{company_id}/retry", { params: { path: { company_id: companyId } } })) : undefined}
          onSaved={() => {
            setPanel(null);
            onChanged();
          }}
        />
      )}
      {panel === "consent" && (
        <ConsentForm
          contactId={contact.id}
          onClose={() => setPanel(null)}
          onSaved={() => {
            setPanel(null);
            onChanged();
          }}
        />
      )}
      {confirm.error && (
        <div className="mt-2">
          <Problem error={confirm.error} />
        </div>
      )}
      {choosing && (
        <Confirm title={`Write to ${contact.full_name ?? "this person"} instead?`} confirmLabel="Write to them" busy={choose.isPending} error={choose.error} onClose={() => setChoosing(false)} onConfirm={() => choose.mutate()}>
          <p>They are put first. An email waiting for review (or approved and not yet in your mailbox) is cancelled, and the lead goes back to the email step, which reuses an address it already has before paying for a new one.</p>
        </Confirm>
      )}
      {removing && (
        <Confirm title={`Remove ${contact.full_name ?? "this person"} from this lead?`} confirmLabel="Remove" busy={remove.isPending} error={remove.error} onClose={() => setRemoving(false)} onConfirm={() => remove.mutate()}>
          <p>Use this for someone who does not work here, such as a wrong match from a search. Their card, addresses and consents are deleted; nothing goes on the do-not-contact list.</p>
        </Confirm>
      )}
      {suppressing && (
        <Confirm title={`Never contact ${contact.full_name ?? "this person"} again?`} confirmLabel="Suppress" busy={suppress.isPending} error={suppress.error} onClose={() => setSuppressing(false)} onConfirm={() => suppress.mutate()}>
          <p>Their address goes on the do-not-contact list, their unsent emails are cancelled, and any draft waiting in your mailbox is deleted. This cannot be undone here.</p>
        </Confirm>
      )}
    </li>
  );
}

/** Correct a person or give them a new address. If the email step had failed, it is retried after. */
function EditPerson({ contact, retry, onSaved }: { contact: Contact; retry?: () => Promise<unknown>; onSaved: () => void }) {
  const [name, setName] = useState(contact.full_name ?? "");
  const [title, setTitle] = useState(contact.title ?? "");
  const [email, setEmail] = useState("");
  const hasAddress = contact.emails.some((e) => e.email);
  const current = contact.emails.find((e) => e.is_primary)?.email;
  const save = useMutation({
    mutationFn: async () => {
      await ok(
        client.PATCH("/api/contacts/{contact_id}", {
          params: { path: { contact_id: contact.id } },
          body: { full_name: name.trim(), title: title.trim(), email: email.trim() || undefined },
        }),
      );
      if (retry) await retry();
    },
    onSuccess: onSaved,
  });
  return (
    <div className="mt-3 rounded-lg border border-line bg-surface-low p-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="First and last name">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Job title">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field
          label={hasAddress ? "New work email" : "Work email"}
          hint={hasAddress ? `Replaces ${current ?? "the current address"} as the one written to; the old one is kept as history.` : "Optional; blank means it is looked up."}
        >
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <Button size="sm" busy={save.isPending} disabled={!name.trim()} onClick={() => save.mutate()}>
          {retry ? "Save and retry the email step" : "Save"}
        </Button>
        <Problem error={save.error} />
      </div>
    </div>
  );
}

function ConsentForm({ contactId, onClose, onSaved }: { contactId: string; onClose: () => void; onSaved: () => void }) {
  const [basis, setBasis] = useState<Basis>("express");
  const [evidence, setEvidence] = useState("");
  const save = useMutation({
    mutationFn: () => ok(client.POST("/api/contacts/{contact_id}/consents", { params: { path: { contact_id: contactId } }, body: { basis, evidence: evidence.trim() } })),
    onSuccess: onSaved,
  });
  return (
    <div className="mt-3 rounded-lg border border-line bg-surface-low p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Basis">
          <Select value={basis} onChange={(e) => setBasis(e.target.value as Basis)}>
            {BASES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Evidence" hint="Where the consent came from. It is kept with the record.">
          <Textarea rows={2} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Button size="sm" busy={save.isPending} disabled={!evidence.trim()} onClick={() => save.mutate()}>
          Save consent
        </Button>
        <Button size="sm" variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Problem error={save.error} />
      </div>
    </div>
  );
}

/**
 * Someone the operator knows at the company. Ticking consent records it in the same step, and on
 * a lead held for consent then releases the hold so the lead carries on.
 */
function AddPerson({ company, onAdded }: { company: Company; onAdded: () => void }) {
  const [name, setName] = useState("");
  const [title, setTitle] = useState("");
  const [email, setEmail] = useState("");
  const [consented, setConsented] = useState(false);
  const [basis, setBasis] = useState<Basis>("express");
  const [evidence, setEvidence] = useState("");
  const heldForConsent = company.status === "held" && (company.hold_reason === "consent_required" || company.hold_reason === "entity_unknown");
  // Decided when the person is added: the hold is released by then, so the page no longer says it was held.
  const [doneText, setDoneText] = useState("Person added.");
  const add = useMutation({
    onMutate: () => setDoneText(consented && heldForConsent ? "Added, and the hold is released. The lead carries on at the next run." : "Person added."),
    mutationFn: async () => {
      await ok(
        client.POST("/api/companies/{company_id}/people", {
          params: { path: { company_id: company.id } },
          body: {
            full_name: name.trim(),
            title: title.trim() || undefined,
            email: email.trim() || undefined,
            consent_basis: consented ? basis : undefined,
            consent_evidence: consented ? evidence.trim() : undefined,
          },
        }),
      );
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
  // The address finders need a first and a last name unless the work email is given.
  const needsFullName = name.trim().split(/\s+/).length < 2 && email.trim() === "";
  const ready = name.trim() !== "" && !needsFullName && (!consented || evidence.trim() !== "");
  return (
    <Card id="add-person" tour="lead-add-person" tone={heldForConsent ? "attention" : undefined} title="Add a person" subtitle={`Someone you know at ${company.name ?? company.domain}. They are tried first when an email is written${heldForConsent ? ", and their consent is what this lead is waiting for" : ""}.`}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Name" hint={needsFullName && name.trim() ? "First and last name, or give their work email, so the address can be found." : undefined}>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="First and last name" />
        </Field>
        <Field label="Job title (optional)">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </Field>
        <Field label="Work email (optional)" hint="Blank means it is looked up and verified.">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </Field>
      </div>
      <div className="mt-3">
        <Checkbox checked={consented} onChange={setConsented} label="This person has given consent to be contacted" hint="Only tick this if you can show where it came from." />
      </div>
      {consented && (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <Field label="Basis">
            <Select value={basis} onChange={(e) => setBasis(e.target.value as Basis)}>
              {BASES.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Evidence" hint="Where the consent came from. It is kept with the record.">
            <Textarea rows={2} value={evidence} onChange={(e) => setEvidence(e.target.value)} />
          </Field>
        </div>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button busy={add.isPending} disabled={!ready} onClick={() => add.mutate()}>
          <UserPlus className="size-3.5" aria-hidden /> {consented && heldForConsent ? "Add person and release the hold" : "Add person"}
        </Button>
        <SaveNote mutation={add} done={doneText} />
      </div>
    </Card>
  );
}

function Research({ company }: { company: Company }) {
  const research = (company.research ?? {}) as Record<string, unknown>;
  const hooks = (research.hooks as string[] | undefined) ?? [];
  const answers = Object.entries(company.research_answers ?? {});
  const decision = (company.policy_decision ?? {}) as { outcome?: string; rule?: string; policy_version?: number; reasons?: string[] };
  if (!research.summary && hooks.length === 0 && answers.length === 0 && !company.fit_reason) return null;
  return (
    <Card title="Research">
      {Boolean(research.summary) && <p className="text-[13px] leading-relaxed">{String(research.summary)}</p>}
      {company.fit_reason && (
        <p className="mt-2 text-xs text-muted">
          <strong className="text-ink">Fit {company.fit_score}/100:</strong> {company.fit_reason}
        </p>
      )}
      {hooks.length > 0 && (
        <>
          <Label className="mb-1 mt-3">Findings</Label>
          <ul className="list-disc space-y-0.5 pl-4 text-[13px]">
            {hooks.map((hook) => (
              <li key={hook}>{hook}</li>
            ))}
          </ul>
        </>
      )}
      {answers.length > 0 && (
        <>
          <Label className="mb-1 mt-3">Your research questions</Label>
          <dl className="space-y-1.5 text-[13px]">
            {answers.map(([q, a]) => (
              <div key={q}>
                <dt className="text-xs text-muted">{q}</dt>
                <dd>{String(a)}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      {decision.outcome && (
        <p className="mt-3 border-t border-line pt-2 text-xs text-muted">
          Country rule: {words(decision.rule ?? decision.outcome)}
          {decision.policy_version != null && ` (version ${decision.policy_version})`}
          {decision.reasons && decision.reasons.length > 0 && ` · ${decision.reasons.join("; ")}`}
        </p>
      )}
    </Card>
  );
}

/** Edit what the operator may change. A save marks the field as theirs: the engine keeps it. */
function EditLead({ company, campaigns, onSaved }: { company: Company; campaigns: Schemas["CampaignOut"][]; onSaved: () => void }) {
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
    <Card tour="lead-edit" title="Edit this lead" subtitle="What you save is marked as yours and kept.">
      <div className="space-y-3">
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Country" hint="Two letters, such as GB">
            <Input value={country} maxLength={2} onChange={(e) => setCountry(e.target.value.toUpperCase())} className="font-mono uppercase" />
          </Field>
          <Field label="Priority" hint="1 first, 9 last">
            <Input type="number" min={1} max={9} value={priority} onChange={(e) => setPriority(e.target.value)} />
          </Field>
        </div>
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
        <div className="flex flex-wrap items-center gap-3">
          <Button busy={save.isPending} onClick={() => save.mutate()}>
            Save changes
          </Button>
          {!stale && <SaveNote mutation={save} />}
        </div>
        {stale && <Callout tone="attention">Someone or something changed this lead since you opened it. Reload the page and try again.</Callout>}
      </div>
    </Card>
  );
}

function DangerZone({ company }: { company: Company }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [dialog, setDialog] = useState<"suppress" | "delete" | null>(null);
  const [block, setBlock] = useState(false);
  const [notice, setNotice] = useState<ReactNode>(null);
  const path = { params: { path: { company_id: company.id } } };
  const refreshAll = () => {
    for (const key of ["companies", "status", "review", "lead", "journey", "timeline", "waterfall", "suppressions"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  const suppress = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/suppress", path)),
    onSuccess: (result) => {
      setDialog(null);
      setNotice(`Suppressed. ${result.messages_cancelled} unsent email(s) cancelled, ${result.drafts_deleted} draft(s) deleted.${result.drafts_left.length ? ` ${result.drafts_left.length} draft(s) could not be deleted; remove them from your Drafts folder.` : ""}`);
      refreshAll();
    },
  });
  const remove = useMutation({
    mutationFn: (typed: string) => ok(client.POST("/api/companies/{company_id}/delete", { ...path, body: { confirm_domain: typed, also_suppress_domain: block } })),
    onSuccess: async (result) => {
      if (result.drafts_left.length > 0) window.alert(`The lead is deleted, but ${result.drafts_left.length} draft(s) could not be removed from your mailbox. Delete them from the Drafts folder.`);
      // Leave first, then forget this lead's data: asking the server for it again would only 404.
      await navigate({ to: "/leads" });
      for (const key of ["lead", "timeline", "waterfall", "journey"]) queryClient.removeQueries({ queryKey: [key, company.id] });
      for (const key of ["companies", "status", "review", "suppressions"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  return (
    <Card tour="lead-danger" tone="error" title={<span className="text-error">Danger zone</span>}>
      <div className="space-y-4 text-[13px]">
        <div>
          <div className="font-medium">Do not contact this company</div>
          <p className="mt-0.5 text-xs text-muted">Everyone at {company.domain} goes on the do-not-contact list; unsent emails are cancelled.</p>
          <Button variant="secondary" size="sm" className="mt-2" onClick={() => setDialog("suppress")}>
            <ShieldOff className="size-3.5" aria-hidden /> Suppress this domain
          </Button>
          {notice && <p className="mt-2 text-xs text-good">{notice}</p>}
        </div>
        <div className="border-t border-line pt-4">
          <div className="font-medium">Delete this lead</div>
          <p className="mt-0.5 text-xs text-muted">Removes the company, its people, emails, notes and history, and any draft in your mailbox. Spend stays in the cost totals. A lead that has been emailed cannot be deleted: suppress it instead.</p>
          <Button variant="danger" size="sm" className="mt-2" onClick={() => setDialog("delete")}>
            <Trash2 className="size-3.5" aria-hidden /> Delete permanently…
          </Button>
        </div>
      </div>
      {dialog === "suppress" && (
        <Confirm title={`Never contact anyone at ${company.domain}?`} confirmLabel="Suppress domain" busy={suppress.isPending} error={suppress.error} onClose={() => setDialog(null)} onConfirm={() => suppress.mutate()}>
          <p>The domain goes on the do-not-contact list for good. Unsent emails are cancelled and drafts waiting in your mailbox are deleted.</p>
        </Confirm>
      )}
      {dialog === "delete" && (
        <Confirm title={`Delete ${company.name ?? company.domain}?`} confirmLabel="Delete permanently" typed={company.domain} busy={remove.isPending} error={remove.error} onClose={() => setDialog(null)} onConfirm={(typed) => remove.mutate(typed)}>
          <p>This cannot be undone. One line records that the lead was deleted, with no personal detail.</p>
          <Checkbox checked={block} onChange={setBlock} label={`Also never contact ${company.domain} again`} hint="So it cannot be added back by mistake." />
        </Confirm>
      )}
    </Card>
  );
}

function summary(data: Record<string, unknown>): string {
  return ["field", "from", "to", "reason", "hold_reason", "error"]
    .filter((key) => data[key])
    .map((key) => `${words(key)}: ${words(String(data[key]))}`)
    .join(", ");
}
