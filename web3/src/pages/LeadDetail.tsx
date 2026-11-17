import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams, useRouterState, useSearch } from "@tanstack/react-router";
import { Tabs } from "../ui/overlay";
import { JourneyView } from "./LeadJourney";
import { ExternalLink, GitFork, Globe2, Mail, RefreshCw, ShieldOff, Trash2, Unlock, UserPlus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { ApiProblem, client, ok, type Schemas } from "../api/client";
import { DirectoryCard } from "../components/DirectoryCard";
import { FitBadge } from "../components/FitBadge";
import { PolicySkip } from "../components/PolicySkip";
import { SkipCheck } from "../components/SkipCheck";
import { StatusBadge } from "../components/StatusBadge";
import {
  Button,
  buttonClass,
  Callout,
  Card,
  Checkbox,
  Confirm,
  Dialog,
  Empty,
  Field,
  Input,
  Label,
  PageHeader,
  Problem,
  QueryState,
  SaveNote,
  Sections,
  Select,
  Skeleton,
  StartNow,
  Table,
  Td,
  Textarea,
  Th,
} from "../ui/compat";
import { cx } from "../lib/cx";
import { ago, usd, when, words } from "../lib/format";
import { activityDays } from "../lib/activity";
import { isViewing, useCurrent } from "../app/session";
import { LinkedInDraftCard } from "../components/LinkedInDraft";
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
  const tab = useSearch({ from: "/leads/$companyId" }).tab ?? "overview";
  const navigate = useNavigate({ from: "/leads/$companyId" });
  const path = { params: { path: { company_id: companyId } } };
  const refresh = useRefreshLead();
  const lead = useQuery({ queryKey: ["lead", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}", path)) });
  const timeline = useQuery({ queryKey: ["timeline", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/timeline", path)) });
  const waterfall = useQuery({ queryKey: ["waterfall", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/waterfall", path)) });
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });

  const retry = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/retry", path)), onSuccess: refresh });
  const requalify = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/requalify", path)), onSuccess: refresh });
  const [researching, setResearching] = useState(false);
  const [researchQueued, setResearchQueued] = useState(false);
  const researchAgain = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/research-again", path)),
    onSuccess: () => {
      setResearching(false);
      setResearchQueued(true);
      refresh();
    },
  });

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
  const here = contacts.filter((c) => c.status !== "not_here");
  const away = contacts.filter((c) => c.status === "not_here");
  const hold = company.hold_reason ? describeHold(company.hold_reason) : null;
  const countryBlocked = (company.policy_decision as { outcome?: string } | null)?.outcome === "block";
  // Only the times the engine tried to overwrite a value you set: yours was kept, theirs is shown.
  const changes = (timeline.data ?? []).filter((e) => e.type === "field_changed" && e.data.applied === false);
  const emailStepFailed = company.status === "failed" && company.failed_stage === "email";
  // The person the email waiting for review (or approved) is written to.
  const liveRecipient = messages.find((m) => m.state === "generated" || m.state === "approved")?.contact_id;
  // Where the page expects the operator to act on people, the card is open for them.
  const peopleNeeded = (company.status === "failed" && (company.failed_stage === "contacts" || company.failed_stage === "email")) || (company.status === "held" && hold?.action === "person");
  const recipientName = contacts.find((c) => c.id === liveRecipient)?.full_name;
  const pausedCampaign = (campaigns.data ?? []).find((c) => c.id === company.campaign_id && c.status !== "active");
  const calls = waterfall.data ?? [];
  const spent = calls.reduce((n, c) => n + c.cost_micro_usd, 0);

  return (
    <Sections>
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
              <a href={`https://${company.domain}`} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-mono text-small hover:text-primary">
                {company.domain} <ExternalLink className="size-3" aria-hidden />
              </a>
              <span className="text-small">Country {company.country_code ?? "unknown"}</span>
              <span className="inline-flex items-center gap-1 text-small">
                Fit <FitBadge score={company.fit_score} hot={company.hot} />
                {company.fit_score == null && "?"}
              </span>
              <span className="text-small">Priority {company.priority}</span>
              <span className="text-small">Added {ago(company.created_at)}</span>
            </span>
          }
          actions={
            <>
              <Link to="/leads/$companyId" params={{ companyId }} search={{ tab: "journey" }} className={buttonClass("secondary")}>
                <GitFork className="size-3.5" aria-hidden /> Journey
              </Link>
              {!NOT_RESEARCHABLE.has(company.status) && (
                <Button data-tour="lead-research-again" variant="secondary" onClick={() => setResearching(true)}>
                  <RefreshCw className="size-3.5" aria-hidden /> Research again
                </Button>
              )}
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

        {researching && (
          <Confirm
            title={`Research ${company.name ?? company.domain} again?`}
            confirmLabel="Research again"
            busy={researchAgain.isPending}
            error={researchAgain.error}
            onClose={() => setResearching(false)}
            onConfirm={() => researchAgain.mutate()}
          >
            <p>The next run, within 15 minutes or when you start one, reads their site and searches the news again (a few cents), then checks the fit, the people, the address and writes the email afresh.</p>
            <p className="mt-2">
              An email waiting for review or approved but not yet in your mailbox is cancelled. What you set yourself is kept: the name, country, people, addresses and consent. Addresses already found are reused at no cost.
            </p>
          </Confirm>
        )}

        <div data-tour="lead-header" className="mb-5 flex flex-wrap items-center gap-2">
          <StatusBadge status={describe(leadStatus, company.status)} />
          {hold && <span className="rounded-full bg-attention-soft px-2 py-0.5 text-small font-medium text-attention">{hold.label}</span>}
          <span className="rounded-full bg-surface-3 px-2 py-0.5 text-small">company type: {words(company.legal_entity_type)}</span>
          {company.created_at && (
            <span className="text-small text-muted" title={when(company.created_at)}>
              Added {ago(company.created_at)} ({words(company.source)})
            </span>
          )}
          {company.updated_at && (
            <span className="text-small text-muted" title={when(company.updated_at)}>
              · last changed {ago(company.updated_at)}
            </span>
          )}
          {company.manual_fields.length > 0 && <span className="text-small text-muted">Set by you, kept as you set it: {company.manual_fields.map(words).join(", ")}</span>}
        </div>

        <div className="mb-5 space-y-3">
          {researchQueued && company.status === "new" && (
            <p className="flex flex-wrap items-center gap-2 text-small text-muted">
              Queued for research again, within 15 minutes, or now: <StartNow />
            </p>
          )}
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
          {pausedCampaign && (
            <Callout tone="attention" title={`Its campaign, ${pausedCampaign.name}, is paused`}>
              This lead waits where it is until that campaign is switched on again under Campaigns.
            </Callout>
          )}
        </div>

        <div className="mb-5">
          <Tabs
            label="Lead views"
            value={tab}
            onChange={(t) => void navigate({ search: { tab: t === "overview" ? undefined : t }, replace: true })}
            tabs={[
              { key: "overview", label: "Overview" },
              { key: "journey", label: "Journey" },
              { key: "activity", label: "Activity", count: timeline.data?.length },
            ]}
          />
        </div>
        {tab === "journey" && <JourneyView companyId={companyId} />}
        {tab === "activity" && (
          <Activity
            events={timeline.data ?? []}
            pending={timeline.isPending}
            error={timeline.error}
            names={Object.fromEntries(contacts.map((c) => [c.id, c.full_name ?? "A person"]))}
            fit={company.fit_score ?? null}
          />
        )}
        <div hidden={tab !== "overview"} className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div className="flex min-w-0 flex-col gap-5">
            <Card
              collapsible
              forceOpen={peopleNeeded}
              tour="lead-people"
              title={`People and addresses (${contacts.length})`}
              subtitle={`${recipientName ? `The email is to ${recipientName}. ` : ""}In rank order: the first usable person gets the email.`}
            >
              {contacts.length === 0 ? (
                <Empty title="No people yet">Research finds people on the company's site; or add someone you know below.</Empty>
              ) : (
                <>
                  <ul className="divide-y divide-line">
                    {here.map((contact) => (
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
                  {away.length > 0 && (
                    <details className="mt-3 rounded-lg border border-line" data-tour="lead-people-away">
                      <summary className="cursor-pointer px-3 py-2 text-small font-medium text-muted hover:bg-surface-2">
                        {away.length} found who work elsewhere (set aside, never written to)
                      </summary>
                      <ul className="divide-y divide-line px-3">
                        {away.map((contact) => (
                          <Person key={contact.id} contact={contact} onChanged={refresh} retryAfterEdit={false} company={company} recipient={false} writtenTo={false} />
                        ))}
                      </ul>
                    </details>
                  )}
                </>
              )}
              <CheckPeople company={company} onDone={refresh} />
            </Card>

            <LinkedInCard company={company} contacts={contacts} onChanged={refresh} />

            <DirectoryCard companyId={company.id} />

            <AddPerson company={company} onAdded={refresh} />

            <Card title={`Emails (${messages.length})`}>
              {messages.length === 0 ? (
                <p className="text-small text-muted">Nothing written yet.</p>
              ) : (
                <div className="space-y-2">
                  {messages.map((m) => (
                    <details key={m.id} className="group rounded-lg border border-line">
                      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2 px-3 py-2.5 hover:bg-surface-2">
                        <span className="font-mono text-small font-semibold">Email {m.step + 1}</span>
                        <span className="min-w-0 flex-1 truncate text-body">{m.subject}</span>
                        <StatusBadge status={describe(messageState, m.state)} />
                        {m.edit_distance != null && <span className="text-label text-muted">edited {Math.round(m.edit_distance * 100)}%</span>}
                        {m.created_at && (
                          <span className="text-label text-muted" title={when(m.created_at)}>
                            written {ago(m.created_at)}
                          </span>
                        )}
                        {m.sent_at && <span className="text-label text-muted" title={when(m.sent_at)}>sent {ago(m.sent_at)}</span>}
                        {m.state === "generated" && (
                          <Link
                            data-tour="lead-open-review"
                            to="/review"
                            search={{ message: m.id }}
                            onClick={(e) => e.stopPropagation()}
                            className={buttonClass("primary", "sm")}
                          >
                            Open in Review
                          </Link>
                        )}
                      </summary>
                      <pre className="whitespace-pre-wrap border-t border-line bg-surface-2 p-3 font-sans text-body leading-relaxed">{m.final_body ?? m.generated_body}</pre>
                    </details>
                  ))}
                </div>
              )}
            </Card>

            <Research company={company} />

            <Card collapsible title="Vendor calls" subtitle={`${calls.length} call${calls.length === 1 ? "" : "s"}, ${usd(spent)} in all. Every paid call made for this lead, in order; a cache hit reused a stored answer at no cost.`}>
              <QueryState query={waterfall}>
                {(steps) =>
                  steps.length === 0 ? (
                    <p className="text-small text-muted">No vendor calls yet.</p>
                  ) : (
                    <Table>
                      <thead>
                        <tr>
                          <Th>When</Th>
                          <Th>Vendor</Th>
                          <Th>Call</Th>
                          <Th>What was asked</Th>
                          <Th>Result</Th>
                          <Th className="text-right">Cost</Th>
                        </tr>
                      </thead>
                      <tbody>
                        {steps.map((step, i) => (
                          <tr key={i}>
                            <Td className="whitespace-nowrap text-small text-muted">{when(step.at)}</Td>
                            <Td className="font-medium">{step.provider}</Td>
                            <Td className="text-small">{words(step.operation)}</Td>
                            <Td className="max-w-xs break-words text-small">
                              {step.asked ? (
                                <>
                                  {step.asked}
                                  {step.contact_id && contacts.find((c) => c.id === step.contact_id)?.full_name && <span className="text-muted"> · for {contacts.find((c) => c.id === step.contact_id)?.full_name}</span>}
                                </>
                              ) : (
                                <span className="text-muted">not recorded</span>
                              )}
                            </Td>
                            <Td>
                              <StatusBadge status={describe(callOutcome, step.outcome)} />
                              {step.got && <div className="mt-0.5 text-label text-muted">{step.got}</div>}
                            </Td>
                            <Td className="text-right font-mono text-small">{usd(step.cost_micro_usd)}</Td>
                          </tr>
                        ))}
                      </tbody>
                    </Table>
                  )
                }
              </QueryState>
            </Card>

            {changes.length > 0 && (
              <Card collapsible title="Your values kept" subtitle="The engine found a different value for something you set. Yours was kept; this is what it found.">
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
                        <Td className="max-w-md truncate font-mono text-small">{JSON.stringify(e.data.new ?? e.data.attempted)}</Td>
                        <Td className="whitespace-nowrap text-small text-muted">{when(e.at)}</Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </Card>
            )}

            <Activity
              events={timeline.data ?? []}
              pending={timeline.isPending}
              error={timeline.error}
              names={Object.fromEntries(contacts.map((c) => [c.id, c.full_name ?? "A person"]))}
              fit={company.fit_score ?? null}
            />
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
                    <li key={note.id} className="rounded-lg bg-surface-2 p-2.5 text-body">
                      {note.body}
                      <div className="mt-1 text-label text-muted">
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
    </Sections>
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
    <Card tone="attention" title={<span className="text-attention">Held: {hold.label}</span>}>
      <p className="text-body">{hold.why}</p>
      <p className="mt-1 text-body font-medium">{hold.fix}</p>
      {hold.action === "person" && (
        <p className="mt-1 text-small text-muted">Releasing the hold does not give consent, so it would only be held again. Consent belongs to a person and is recorded with them.</p>
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
      {suggestion && hold.action === "country" && <p className="mt-2 text-small text-muted">Suggested from the research: {suggestion.evidence}. It is a suggestion, not proof.</p>}
      <p className="mt-2 text-label text-muted">
        The stage that held it runs again within 15 minutes. A country-rule hold is refused while nothing has changed; you can also skip the country rule for this lead under <em>Country rule</em>.
      </p>
      <div className="mt-2 flex items-center gap-2">
        <StartNow />
      </div>
      <Problem error={release.error ?? setCountry.error} className="mt-2" />
    </Card>
  );
}

// Not offered for a lead not yet researched, or one whose email has already left.
const NOT_RESEARCHABLE = new Set(["new", "in_sequence", "replied", "completed", "rejected", "suppressed"]);

// A lead in one of these can be pointed at a different person before the email reaches the mailbox.
const RECIPIENT_CHANGEABLE = new Set(["contacts_found", "email_ready", "copy_ready", "approved", "failed", "held"]);
// Where a person's email can be looked for again: before any email has been written to the lead.
const EMAIL_RETRY = new Set(["contacts_found", "email_ready", "failed", "held"]);
const WORKABLE = new Set(["candidate", "active"]);

/** The LinkedIn note and message written for each confirmed person, to paste into LinkedIn by hand. */
function LinkedInCard({ company, contacts, onChanged }: { company: Company; contacts: Contact[]; onChanged: () => void }) {
  const { workspace } = useCurrent();
  const queryClient = useQueryClient();
  const drafts = useQuery({ queryKey: ["linkedin-lead", company.id], queryFn: () => ok(client.GET("/api/companies/{company_id}/linkedin", { params: { path: { company_id: company.id } } })) });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["linkedin-lead", company.id] });
    void queryClient.invalidateQueries({ queryKey: ["linkedin"] });
    onChanged();
  };
  const write = useMutation({
    mutationFn: (contactId: string) => ok(client.POST("/api/contacts/{contact_id}/linkedin", { params: { path: { contact_id: contactId } } })),
    onSuccess: refresh,
  });
  const byContact = new Map((drafts.data ?? []).map((d) => [d.contact_id, d]));
  const person = (id: string) => contacts.find((c) => c.id === id);
  // Confirmed people with a profile and no message yet: one button each.
  const unwritten = contacts.filter((c) => WORKABLE.has(c.status) && c.linkedin_url && !byContact.has(c.id));
  const viewing = isViewing(workspace);
  const held = company.hold_reason === "linkedin_contacted";
  return (
    <Card
      tour="lead-linkedin"
      title={`LinkedIn (${drafts.data?.length ?? 0})`}
      subtitle="A connection note and a first message for each confirmed person, written before their email is found. Copy them into LinkedIn yourself: nothing is sent from here."
    >
      {held && (
        <Callout tone="attention" title="The email waits for you">
          You messaged someone here on LinkedIn, so the email is on hold. Release the hold above when you want it written as well.
        </Callout>
      )}
      <QueryState query={drafts}>
        {(rows) => (
          <div className="space-y-3">
            {rows.length === 0 && unwritten.length === 0 && (
              <p className="text-small text-muted">Nothing yet. A message is written for a confirmed decision-maker who has a LinkedIn profile; use Find LinkedIn on a person, and confirm that they work here, to get one.</p>
            )}
            {rows.map((draft) => (
              <LinkedInDraftCard key={draft.id} draft={draft} person={person(draft.contact_id)?.full_name} profile={person(draft.contact_id)?.linkedin_url} readOnly={viewing} onChanged={refresh} />
            ))}
            {!viewing &&
              unwritten.map((c) => (
                <div key={c.id} className="flex flex-wrap items-center gap-3 text-small">
                  <span className="font-medium">{c.full_name}</span>
                  <Button size="sm" variant="secondary" busy={write.isPending && write.variables === c.id} onClick={() => write.mutate(c.id)}>
                    Write LinkedIn message
                  </Button>
                </div>
              ))}
            <Problem error={write.error} />
          </div>
        )}
      </QueryState>
    </Card>
  );
}

/** Look again at who a search found: one search per person and one model call, then people whose
 * profile says they work elsewhere are set aside. Nobody you confirmed or wrote to is touched. */
function CheckPeople({ company, onDone }: { company: Company; onDone: () => void }) {
  const { workspace } = useCurrent();
  const check = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/check-people", { params: { path: { company_id: company.id } } })),
    onSuccess: onDone,
  });
  if (isViewing(workspace)) return null;
  return (
    <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-line pt-3" data-tour="lead-check-people">
      <Button size="sm" variant="secondary" busy={check.isPending} onClick={() => check.mutate()} title="One search per person and one model call: sets aside people whose profile says they work elsewhere">
        Check who works here
      </Button>
      {check.data && (
        <span className="text-small text-muted" role="status">
          {check.data.checked === 0
            ? "Nobody to check."
            : `Checked ${check.data.checked}: ${check.data.works_here} work here, ${check.data.not_here} set aside, ${check.data.unsure} still unsure.`}
        </span>
      )}
      <Problem error={check.error} />
    </div>
  );
}

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
  const queryClient = useQueryClient();
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
  const notHere = contact.status === "not_here";
  const markNotHere = useMutation({
    mutationFn: () => ok(client.POST("/api/contacts/{contact_id}/not-here", { params: { path: { contact_id: contact.id } }, body: { note: "" } })),
    onSuccess: onChanged,
  });
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
  const findLinkedin = useMutation({
    mutationFn: () => ok(client.POST("/api/contacts/{contact_id}/find-linkedin", { params: { path: { contact_id: contact.id } } })),
    onSuccess: (found) => {
      if (found.url) onChanged();
    },
  });
  const retryEmail = useMutation({
    mutationFn: () => ok(client.POST("/api/contacts/{contact_id}/retry-email", { params: { path: { contact_id: contact.id } } })),
    onSuccess: () => {
      for (const key of ["runs", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
      onChanged();
    },
  });
  const canRetryEmail = !gone && WORKABLE.has(contact.status) && EMAIL_RETRY.has(company.status);
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex size-6 items-center justify-center rounded-full bg-primary-soft font-mono text-label font-semibold text-primary">{contact.rank}</span>
            <span className="font-semibold">{contact.full_name ?? "(no name)"}</span>
            {contact.title && <span className="text-small text-muted">{contact.title}</span>}
            {unconfirmed && (
              <span className="rounded-full bg-attention-soft px-2 py-0.5 text-label font-medium text-attention" title={contact.placement_note ?? "A search found this person, but their profile does not clearly say they work here."}>
                Unconfirmed: check they work here
              </span>
            )}
            {notHere && <span className="rounded-full bg-surface-3 px-2 py-0.5 text-label font-medium text-muted">Works elsewhere</span>}
            {!unconfirmed && !notHere && contact.status !== "active" && contact.status !== "candidate" && <span className="rounded bg-surface-3 px-1.5 text-label">{words(contact.status)}</span>}
            {recipient && <span className="rounded-full bg-primary-soft px-2 py-0.5 text-label font-medium text-primary">The email is to this person</span>}
            {contact.linkedin_url ? (
              <a href={contact.linkedin_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-label font-medium text-primary hover:underline">
                LinkedIn <ExternalLink className="size-3" aria-hidden />
              </a>
            ) : (
              !gone && (
                <button
                  type="button"
                  onClick={() => findLinkedin.mutate()}
                  disabled={findLinkedin.isPending || !contact.full_name}
                  className="text-label font-medium text-primary hover:underline disabled:opacity-60"
                  title="One search for this person's LinkedIn profile"
                >
                  {findLinkedin.isPending ? "Searching…" : "Find LinkedIn"}
                </button>
              )
            )}
            {findLinkedin.isSuccess && !findLinkedin.data.url && <span className="text-label text-muted">No clear match found</span>}
            {contact.created_at && (
              <span className="text-label text-muted" title={when(contact.created_at)}>
                found {ago(contact.created_at)}
              </span>
            )}
          </div>
          {(unconfirmed || notHere) && contact.placement_note && <p className="mt-1 pl-8 text-small text-muted">{contact.placement_note}</p>}
          <ul className="mt-1.5 space-y-1 pl-8">
            {contact.emails.map((email) => (
              <li key={email.id} className="flex flex-wrap items-center gap-2 text-small">
                <Mail className="size-3.5 text-muted" aria-hidden />
                <span className="font-mono">{email.email ?? "(erased)"}</span>
                <StatusBadge status={describe(emailStatus, email.status)} />
                <span className="text-muted">
                  {words(email.provenance)}
                  {email.found_by && ` · found by ${email.found_by}`}
                  {email.verified_by && ` · checked by ${email.verified_by}`}
                  {email.verified_at && ` ${ago(email.verified_at)}`}
                </span>
                {!gone && WORKABLE.has(contact.status) && <SkipCheck email={email} personName={contact.full_name} />}
              </li>
            ))}
            {contact.emails.length === 0 && <li className="text-small text-muted">No address yet.</li>}
            {contact.refresh_email && <li className="text-small font-medium text-primary">Email search queued: it runs within 15 minutes.</li>}
          </ul>
        </div>
        {!gone && (
          <div className="flex flex-wrap gap-1">
            {(unconfirmed || notHere) && (
              <Button size="sm" variant={notHere ? "secondary" : "primary"} busy={confirm.isPending} onClick={() => confirm.mutate()}>
                {notHere ? "They do work here" : "Confirm they work here"}
              </Button>
            )}
            {(unconfirmed || WORKABLE.has(contact.status)) && !writtenTo && (
              <Button variant="ghost" size="sm" busy={markNotHere.isPending} onClick={() => markNotHere.mutate()} title="Keep them on the lead, set aside; they are never written to">
                Doesn't work here
              </Button>
            )}
            <Button variant="ghost" size="sm" onClick={() => setPanel(panel === "edit" ? null : "edit")}>
              Edit
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setPanel(panel === "consent" ? null : "consent")}>
              Record consent
            </Button>
            {canRetryEmail && !contact.refresh_email && (
              <Button variant="ghost" size="sm" busy={retryEmail.isPending} onClick={() => retryEmail.mutate()} title="Search for this person's email again, with fresh answers from the vendors">
                <RefreshCw className="size-3.5" aria-hidden /> Find email again
              </Button>
            )}
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
      <Problem error={findLinkedin.error ?? retryEmail.error ?? markNotHere.error ?? confirm.error} className="mt-2" />
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
    <div className="mt-3 rounded-lg border border-line bg-surface-2 p-3">
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
    <div className="mt-3 rounded-lg border border-line bg-surface-2 p-3">
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
  const hash = useRouterState({ select: (state) => state.location.hash });
  const heldForConsent = company.status === "held" && (company.hold_reason === "consent_required" || company.hold_reason === "entity_unknown");
  // Decided when the person is added: the hold is released by then, so the page no longer says it was held.
  const [doneText, setDoneText] = useState("Person added.");
  const add = useMutation({
    onMutate: () => setDoneText(consented && heldForConsent ? "Added, and the hold is released. The lead carries on within 15 minutes." : "Person added."),
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
    <Card id="add-person" collapsible forceOpen={heldForConsent || hash === "add-person"} tour="lead-add-person" tone={heldForConsent ? "attention" : undefined} title="Add a person" subtitle={`Someone you know at ${company.name ?? company.domain}. They are tried first when an email is written${heldForConsent ? ", and their consent is what this lead is waiting for" : ""}.`}>
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
        {add.isSuccess && consented && heldForConsent && <StartNow />}
      </div>
    </Card>
  );
}

type NewsItem = { date?: string; headline: string; detail?: string; matters?: string; url: string };

function NewsList({ title, items }: { title: string; items: NewsItem[] }) {
  if (items.length === 0) return null;
  return (
    <>
      {title && <Label className="mb-1 mt-3">{title}</Label>}
      <ul className="space-y-2 text-body">
        {items.map((item) => (
          <li key={item.url}>
            <a href={item.url} target="_blank" rel="noreferrer" className="font-medium text-primary hover:underline">
              {item.headline}
            </a>
            {item.date && <span className="ml-2 font-mono text-label text-muted">{item.date}</span>}
            {item.detail && <div className="text-small text-muted">{item.detail}</div>}
            {item.matters && <div className="text-small text-muted">Why it matters: {item.matters}</div>}
          </li>
        ))}
      </ul>
    </>
  );
}

type Criterion = { id: string; kind: string; criterion: string; weight: number; verdict: string; evidence?: string; source?: string };
type QualificationData = { criteria?: Criterion[]; why_now?: string; risks?: string[] };

const KIND = { must_have: "Must have", signal: "Sign they may buy now", disqualifier: "Rules them out" } as Record<string, string>;
const VERDICT = {
  met: { text: "Yes", tone: "text-good" },
  not_met: { text: "No", tone: "text-error" },
  unknown: { text: "Not known", tone: "text-muted" },
} as Record<string, { text: string; tone: string }>;

/** The brief's criteria one by one: what research found for each, and where. */
function Qualification({ data }: { data: QualificationData }) {
  const criteria = data.criteria ?? [];
  const risks = (data.risks ?? []).filter(Boolean);
  return (
    <div className="mt-2 space-y-2">
      {criteria.length > 0 && (
        <ul className="space-y-1.5 text-body">
          {criteria.map((c) => {
            const verdict = VERDICT[c.verdict] ?? VERDICT.unknown;
            return (
              <li key={c.id} className="flex gap-2">
                <span className={`w-16 shrink-0 text-small font-medium ${verdict.tone}`}>{verdict.text}</span>
                <div className="min-w-0">
                  <div>
                    {c.criterion}
                    <span className="ml-1.5 text-label text-muted">
                      {KIND[c.kind] ?? c.kind}
                      {c.weight > 1 ? ` · counts ${c.weight}` : ""}
                    </span>
                  </div>
                  {c.evidence && (
                    <div className="text-small text-muted">
                      {c.evidence}
                      {c.source && (
                        <a href={c.source} target="_blank" rel="noreferrer" className="ml-1 text-primary hover:underline">
                          source
                        </a>
                      )}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {data.why_now && (
        <p className="text-body">
          <span className="font-medium">Why now: </span>
          {data.why_now}
        </p>
      )}
      {risks.length > 0 && (
        <div className="text-body">
          <span className="font-medium">Risks: </span>
          {risks.join("; ")}
        </div>
      )}
    </div>
  );
}

/** A titled block of the research, with a rule above it so the card reads as sections. */
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line pt-3 first:border-0 first:pt-0">
      <Label className="mb-1.5">{title}</Label>
      {children}
    </section>
  );
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-1 pl-4 text-body leading-relaxed">
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </ul>
  );
}

/** Everything research found, grouped under headings; nothing is cut short. */
function Research({ company }: { company: Company }) {
  const research = (company.research ?? {}) as Record<string, unknown>;
  const list = (key: string) => ((research[key] as string[] | undefined) ?? []).filter(Boolean);
  const hooks = list("hooks");
  const products = list("products");
  const siteNews = list("news");
  const tech = list("tech");
  const newsItems = (research.news_items as NewsItem[] | undefined) ?? [];
  const triggers = (research.triggers as NewsItem[] | undefined) ?? [];
  const answers = Object.entries(company.research_answers ?? {});
  const hiring = String(research.hiring ?? "").trim();
  const sector = String(research.sector ?? "").trim();
  const qualification = research.qualification as QualificationData | undefined;
  const decision = (company.policy_decision ?? {}) as { outcome?: string; rule?: string; policy_version?: number; reasons?: string[] };
  const empty = !research.summary && !hooks.length && !products.length && !answers.length && !company.fit_reason && !newsItems.length && !triggers.length;
  if (empty) return null;
  return (
    <Card
      collapsible
      tour="lead-research"
      title="Research"
      subtitle={`${company.fit_score != null ? `Fit ${company.fit_score}/100. ` : ""}${hooks.length + newsItems.length} thing${hooks.length + newsItems.length === 1 ? "" : "s"} worth mentioning${company.updated_at ? `. Last updated ${ago(company.updated_at)}` : ""}`}
    >
      <div className="space-y-3">
        {(Boolean(research.summary) || sector) && (
          <Section title="What they do">
            {sector && <span className="mb-1.5 inline-block rounded-full bg-primary-soft px-2 py-0.5 text-label font-medium text-primary">{sector}</span>}
            {Boolean(research.summary) && <p className="whitespace-pre-line text-body leading-relaxed">{String(research.summary)}</p>}
          </Section>
        )}
        {company.fit_reason && (
          <Section title="How well they fit">
            <p className="text-body leading-relaxed">
              <strong>{company.fit_score}/100.</strong> {company.fit_reason}
            </p>
            {qualification && <Qualification data={qualification} />}
          </Section>
        )}
        {products.length > 0 && (
          <Section title={`Products and services (${products.length})`}>
            <Bullets items={products} />
          </Section>
        )}
        {hooks.length > 0 && (
          <Section title={`Worth mentioning in an email (${hooks.length})`}>
            <Bullets items={hooks} />
          </Section>
        )}
        {siteNews.length > 0 && (
          <Section title={`From their own site (${siteNews.length})`}>
            <Bullets items={siteNews} />
          </Section>
        )}
        {newsItems.length > 0 && (
          <Section title={`Recent news about them (${newsItems.length})`}>
            <NewsList title="" items={newsItems} />
          </Section>
        )}
        {triggers.length > 0 && (
          <Section title={`Market news that may matter to them (${triggers.length})`}>
            <NewsList title="" items={triggers} />
          </Section>
        )}
        {hiring && (
          <Section title="Hiring">
            <p className="whitespace-pre-line text-body leading-relaxed">{hiring}</p>
          </Section>
        )}
        {tech.length > 0 && (
          <Section title="Technology they use">
            <ul className="flex flex-wrap gap-1.5">
              {tech.map((t, i) => (
                <li key={i} className="rounded-md border border-line bg-surface-2 px-2 py-0.5 text-small">
                  {t}
                </li>
              ))}
            </ul>
          </Section>
        )}
        {answers.length > 0 && (
          <Section title="Your research questions">
            <dl className="space-y-2.5 text-body">
              {answers.map(([q, a]) => (
                <div key={q}>
                  <dt className="text-small font-medium text-muted">{q}</dt>
                  <dd className="mt-0.5 whitespace-pre-line leading-relaxed">{String(a) || <span className="text-muted">No answer found.</span>}</dd>
                </div>
              ))}
            </dl>
          </Section>
        )}
        {decision.outcome && (
          <Section title="Country rule">
            <p className="text-small text-muted">
              {words(decision.rule ?? decision.outcome)}
              {decision.policy_version != null && ` (version ${decision.policy_version})`}
              {decision.reasons && decision.reasons.length > 0 && ` · ${decision.reasons.join("; ")}`}
            </p>
          </Section>
        )}
      </div>
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
  const [draftsLeft, setDraftsLeft] = useState<number | null>(null);
  const remove = useMutation({
    mutationFn: (typed: string) => ok(client.POST("/api/companies/{company_id}/delete", { ...path, body: { confirm_domain: typed, also_suppress_domain: block } })),
    onSuccess: async (result) => {
      // Drafts that could not be removed are said first; leaving the page waits for the person to read it.
      if (result.drafts_left.length > 0) {
        setDraftsLeft(result.drafts_left.length);
        return;
      }
      await leave();
    },
  });
  // Leave first, then forget this lead's data: asking the server for it again would only 404.
  const leave = async () => {
    await navigate({ to: "/leads" });
    for (const key of ["lead", "timeline", "waterfall", "journey"]) queryClient.removeQueries({ queryKey: [key, company.id] });
    for (const key of ["companies", "status", "review", "suppressions"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  return (
    <Card collapsible tour="lead-danger" tone="error" title={<span className="text-error">Danger zone</span>}>
      {draftsLeft !== null && (
        <Dialog title="The lead is deleted" onClose={() => void leave()} footer={<Button onClick={() => void leave()}>OK</Button>}>
          <p>{draftsLeft} draft{draftsLeft === 1 ? "" : "s"} could not be removed from your mailbox. Delete {draftsLeft === 1 ? "it" : "them"} from the Drafts folder.</p>
        </Dialog>
      )}
      <div className="space-y-4 text-body">
        <div>
          <div className="font-medium">Do not contact this company</div>
          <p className="mt-0.5 text-small text-muted">Everyone at {company.domain} goes on the do-not-contact list; unsent emails are cancelled.</p>
          <Button variant="secondary" size="sm" className="mt-2" onClick={() => setDialog("suppress")}>
            <ShieldOff className="size-3.5" aria-hidden /> Suppress this domain
          </Button>
          {notice && <p className="mt-2 text-small text-good">{notice}</p>}
        </div>
        <div className="border-t border-line pt-4">
          <div className="font-medium">Delete this lead</div>
          <p className="mt-0.5 text-small text-muted">Removes the company, its people, emails, notes and history, and any draft in your mailbox. Spend stays in the cost totals. A lead that has been emailed cannot be deleted: suppress it instead.</p>
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

/** What happened to the lead, as sentences, newest first. Minor events are behind a toggle. */
function Activity({ events, pending, error, names, fit }: { events: Schemas["TimelineOut"][]; pending: boolean; error: unknown; names: Record<string, string>; fit: number | null }) {
  const [detailed, setDetailed] = useState(false);
  const days = activityDays(events, names, fit, detailed);
  const latest = activityDays(events, names, fit, false)[0]?.lines[0];
  return (
    <Card
      collapsible
      tour="lead-activity"
      title="Activity"
      subtitle={latest ? `${latest.line.text}, ${ago(latest.at)}` : "What has happened to this lead"}
    >
      <Problem error={error} />
      {pending ? (
        <Skeleton rows={3} />
      ) : (
        <>
          {days.length === 0 && <p className="text-small text-muted">Nothing has happened yet.</p>}
          <div className="space-y-4">
            {days.map((day) => (
              <section key={day.label}>
                <h3 className="mb-1.5 text-label font-semibold uppercase tracking-wider text-muted">{day.label}</h3>
                <ol className="relative space-y-2.5 border-l border-line pl-4">
                  {day.lines.map((row, i) => (
                    <li key={i} className="relative">
                      <span className={cx("absolute -left-[21px] top-1.5 size-2.5 rounded-full border-2 border-surface", row.line.tone === "good" ? "bg-good" : row.line.tone === "error" ? "bg-error" : row.line.tone === "attention" ? "bg-attention" : "bg-outline")} aria-hidden />
                      <div className="text-body">
                        {row.line.text}
                        {row.count > 1 && <span className="text-muted"> ×{row.count}</span>}
                        {row.by && <span className="text-small text-muted"> · by {row.by}</span>}
                      </div>
                      <div className="text-label text-muted" title={when(row.at)}>
                        {new Date(row.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            ))}
          </div>
          <button type="button" onClick={() => setDetailed(!detailed)} className="mt-3 text-small font-semibold text-primary hover:underline">
            {detailed ? "Hide details" : "Show details"}
          </button>
        </>
      )}
    </Card>
  );
}
