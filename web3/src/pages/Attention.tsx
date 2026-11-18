/**
 * Needs attention: everything waiting on a person except email review. Tabs with counts; each
 * group is a folding section (the first open) with its plain cause, its fix and a bulk action.
 * Same actions as web2: retry one, by step or all; release; find email again (one or all);
 * use the suggested country and release; resume after waiting for AI credits; confirm websites.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, CheckCircle2, ChevronDown, Clock, Flame, Globe2, RefreshCw, UserPlus, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { client, ok, type Schemas } from "../api/client";
import { cx } from "../lib/cx";
import { ago, credits as aiCredits, words } from "../lib/format";
import { HOLD_REASONS, describeHold } from "../lib/status";
import { STEP_LABEL, day, useUsage } from "../lib/usage";
import { Avatar, Button, buttonClass, Card, Chip, Empty, Input, Mono, PageHeader, Problem, Select, Skeleton } from "../ui/core";
import { FilterChip, SearchBox, SortControl } from "../ui/filters";
import { FitBreakdown, qualificationOf } from "../ui/lead";
import { FitRing } from "../ui/viz";
import { Confirm, Tabs, useToast } from "../ui/overlay";
import { Section, SectionGroup } from "../ui/sections";

type Company = Schemas["CompanyRowOut"];
type Filter = "all" | "held" | "failed" | "confirm" | "credits";
type SortKey = "fit" | "waiting" | "newest" | "company";
type Facets = { q: string; hot: boolean; fit: number | null; step: string; source: string; country: string; sort: SortKey; dir: "asc" | "desc" };
const SORTS = [
  ["fit", "Best fit"],
  ["waiting", "Waiting longest"],
  ["newest", "Newest"],
  ["company", "Company A to Z"],
] as const;
const NATURAL: Record<SortKey, "asc" | "desc"> = { fit: "desc", waiting: "asc", newest: "desc", company: "asc" };
const NO_FACETS: Facets = { q: "", hot: false, fit: null, step: "", source: "", country: "", sort: "fit", dir: "desc" };
const SOURCES = [
  ["discovery", "Found by discovery"],
  ["manual", "Added by you"],
  ["import", "Imported"],
  ["referral", "Referral"],
] as const;

const matches = (c: Company, f: Facets) =>
  (!f.q || [c.name, c.domain, c.summary?.contact_name].some((v) => v?.toLowerCase().includes(f.q.toLowerCase()))) &&
  (!f.hot || c.hot) &&
  (f.fit === null || (c.fit_score ?? -1) >= f.fit) &&
  (!f.step || (c.failed_stage ?? "") === f.step) &&
  (!f.source || c.source === f.source) &&
  (!f.country || c.country_code?.toUpperCase() === f.country);

const order = (a: Company, b: Company, f: Facets) => {
  const sign = f.dir === "asc" ? 1 : -1;
  const key = (c: Company): number | string => (f.sort === "fit" ? (c.fit_score ?? -1) : f.sort === "waiting" ? (c.updated_at ?? "") : f.sort === "newest" ? (c.created_at ?? "") : (c.name ?? c.domain).toLowerCase());
  const [x, y] = [key(a), key(b)];
  return x < y ? -sign : x > y ? sign : 0;
};

const STEP_ORDER = ["research", "gate", "contacts", "email", "copy", "deliver"];
const STEP_NAMES: Record<string, string> = { research: "research", gate: "qualification", contacts: "people", email: "the email address", copy: "writing the email", deliver: "the mailbox", other: "another step" };

function useRefresh() {
  const queryClient = useQueryClient();
  return () => ["companies", "status", "lead", "journey", "waiting", "usage"].forEach((key) => void queryClient.invalidateQueries({ queryKey: [key] }));
}

export function AttentionPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const [facets, setFacets] = useState<Facets>(NO_FACETS);
  // Only what a person can unblock: holds the engine is not working on, and steps that broke on
  // every try. Leads still being retried, and normal "nobody to write to" outcomes, are not here.
  const lists = useQuery({
    queryKey: ["companies", "attention"],
    queryFn: async () => {
      const decision = await ok(client.GET("/api/companies", { params: { query: { bucket: "decision", include: "summary", limit: 200 } } }));
      return { held: decision.items.filter((c) => c.status === "held"), failed: decision.items.filter((c) => c.status === "failed") };
    },
    refetchInterval: 10000,
  });
  const waiting = useQuery({ queryKey: ["waiting"], queryFn: () => ok(client.GET("/api/targets/waiting")) });
  const usage = useUsage();
  const credits = useQuery({ queryKey: ["companies", "credits"], queryFn: () => ok(client.GET("/api/companies", { params: { query: { waiting_for_credits: true, include: "summary", limit: 200 } } })), refetchInterval: 10000 });

  const keep = (list: Company[]) => list.filter((c) => matches(c, facets)).sort((a, b) => order(a, b, facets));
  const everyone = [...(lists.data?.held ?? []), ...(lists.data?.failed ?? [])];
  const held = keep(lists.data?.held ?? []);
  const failed = keep(lists.data?.failed ?? []);
  const confirm = waiting.data ?? [];
  const parked = keep(credits.data?.items ?? []);
  const narrowed = JSON.stringify(facets) !== JSON.stringify(NO_FACETS);
  const countries = [...new Set(everyone.map((c) => c.country_code?.toUpperCase()).filter((v): v is string => !!v))].sort();
  const rows = usage.data?.waiting_rows ?? 0;
  const total = held.length + failed.length + confirm.length + parked.length + rows;
  const groups = HOLD_REASONS.map((r) => [r, held.filter((c) => c.hold_reason === r)] as const).filter(([, list]) => list.length > 0);
  const byStage = STEP_ORDER.map((s) => [s, failed.filter((c) => (c.failed_stage ?? "other") === s)] as const)
    .concat([["other", failed.filter((c) => !STEP_ORDER.includes(c.failed_stage ?? "other"))] as const])
    .filter(([, list]) => list.length > 0);
  const show = (kind: Filter) => filter === "all" || filter === kind;
  const loading = lists.isPending || waiting.isPending;

  return (
    <>
      <PageHeader
        title="Needs a decision"
        subtitle={total ? `${total} lead${total === 1 ? "" : "s"} need a choice only you can make. Everything else runs by itself.` : "Holds, websites to confirm and leads waiting for AI credits land here. Companies that do not fit are not a problem: the engine screens most out."}
        actions={
          filter !== "credits" &&
          failed.length > 1 &&
          byStage.length > 1 && (
            <span data-tour="attention-retry-all">
              <BulkAction ids={failed.map((c) => c.id)} kind="retry" label="Retry every stopped lead" />
            </span>
          )
        }
      />
      <div className="mb-5">
        <Tabs
          label="Show"
          tour="attention-filter"
          value={filter}
          onChange={setFilter}
          tabs={[
            { key: "all", label: "All", count: total },
            { key: "failed", label: "Stopped", count: failed.length },
            { key: "held", label: "On hold", count: held.length },
            { key: "confirm", label: "Websites to confirm", count: confirm.length },
            { key: "credits", label: "Waiting for AI credits", count: parked.length + rows },
          ]}
        />
      </div>

      {everyone.length > 0 && (
        <Card className="mb-5 overflow-hidden p-0" data-tour="attention-facets">
          <div className="flex flex-wrap items-center gap-2 bg-surface-2 p-3">
            <SearchBox label="Search by company, website or person" placeholder="Search company, website or person" value={facets.q} onChange={(q) => setFacets({ ...facets, q })} />
            <FilterChip active={facets.hot} onClick={() => setFacets({ ...facets, hot: !facets.hot })}>
              <Flame className="size-3.5" aria-hidden /> Hot only
            </FilterChip>
            <Select aria-label="Minimum fit" value={facets.fit ?? ""} onChange={(e) => setFacets({ ...facets, fit: e.target.value ? Number(e.target.value) : null })}>
              <option value="">Any fit</option>
              {[40, 60, 70, 80, 90].map((n) => (
                <option key={n} value={n}>
                  Fit {n}+
                </option>
              ))}
            </Select>
            <Select aria-label="Step that stopped" value={facets.step} onChange={(e) => setFacets({ ...facets, step: e.target.value })}>
              <option value="">Any step</option>
              {STEP_ORDER.map((st) => (
                <option key={st} value={st}>
                  Stopped at {STEP_NAMES[st]}
                </option>
              ))}
            </Select>
            <Select aria-label="Source" value={facets.source} onChange={(e) => setFacets({ ...facets, source: e.target.value })}>
              <option value="">Any source</option>
              {SOURCES.map(([v, label]) => (
                <option key={v} value={v}>
                  {label}
                </option>
              ))}
            </Select>
            {countries.length > 1 && (
              <Select aria-label="Country" value={facets.country} onChange={(e) => setFacets({ ...facets, country: e.target.value })}>
                <option value="">Any country</option>
                {countries.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </Select>
            )}
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <SortControl value={facets.sort} options={SORTS} direction={facets.dir} onSort={(sort) => setFacets({ ...facets, sort, dir: NATURAL[sort] })} onDirection={() => setFacets({ ...facets, dir: facets.dir === "asc" ? "desc" : "asc" })} />
              {narrowed && (
                <Button variant="ghost" size="sm" onClick={() => setFacets(NO_FACETS)}>
                  <X className="size-3.5" aria-hidden /> Clear
                </Button>
              )}
            </div>
          </div>
          {narrowed && (
            <p className="px-4 py-2 text-small text-muted">
              Showing {held.length + failed.length + parked.length} of {everyone.length + (credits.data?.items.length ?? 0)} leads.
            </p>
          )}
        </Card>
      )}

      {loading && <Skeleton rows={6} />}
      <Problem error={lists.error ?? waiting.error} />
      {!loading && total === 0 && (
        <Card>
          <Empty art={<CheckCircle2 className="size-12 text-good-dot" />} title="Nothing needs a decision ✨">
            Holds, stopped steps and websites to confirm appear here the moment they need you.
          </Empty>
        </Card>
      )}

      <SectionGroup storageKey={`attention-${filter}`} toolbar={total > 0}>
        {show("failed") &&
          byStage.map(([stage, list]) => (
            <Section
              key={`f-${stage}`}
              id={`failed-${stage}`}
              tone="attention"
              title={`Stopped at ${STEP_NAMES[stage] ?? words(stage)}`}
              summary={`${list.length} lead${list.length === 1 ? "" : "s"} · ${list[0]?.last_error ?? "a step failed"}`}
              chip={<Chip tone="error">{list.length} stopped</Chip>}
              actions={<BulkAction ids={list.map((c) => c.id)} kind="retry" label="Retry all" />}
            >
              <p className="mb-3 text-small text-muted">This step broke on every try (each lead is tried up to 5 times, waiting longer each time). Retry once the cause is fixed.</p>
              <ul className="divide-y divide-line">
                {list.map((c) => (
                  <FailedRow key={c.id} company={c} />
                ))}
              </ul>
            </Section>
          ))}
        {show("held") &&
          groups.map(([reason, list]) => {
            const hold = describeHold(reason);
            return (
              <Section
                key={`h-${reason}`}
                id={`held-${reason}`}
                title={hold.label}
                summary={`${list.length} lead${list.length === 1 ? "" : "s"} · ${hold.why}`}
                chip={<Chip tone="attention">{list.length} held</Chip>}
                actions={reason === "catch_all_unverified" ? <FindAgainAll ids={list.map((c) => c.id)} /> : reason === "linkedin_contacted" ? <BulkAction ids={list.map((c) => c.id)} kind="release" label="Release all" /> : undefined}
              >
                <p className="mb-3 text-small text-muted">
                  {hold.why} {hold.fix}
                </p>
                <ul className="divide-y divide-line">
                  {list.map((c) => (
                    <HeldRow key={c.id} company={c} />
                  ))}
                </ul>
              </Section>
            );
          })}
        {show("confirm") && confirm.length > 0 && (
          <Section id="confirm" title="Websites to confirm" summary={`${confirm.length} uploaded row${confirm.length === 1 ? "" : "s"} need a website before research`} chip={<Chip tone="attention">{confirm.length}</Chip>}>
            <p className="mb-3 text-small text-muted">These were added by name, and the website found is not certain. Confirm it, or give the right one.</p>
            <ul className="divide-y divide-line">
              {confirm.map((row) => (
                <ConfirmRow key={row.id} row={row} />
              ))}
            </ul>
          </Section>
        )}
        {show("credits") && parked.length + rows > 0 && <CreditWait leads={parked} rows={rows} renews={day(usage.data?.period_end)} />}
      </SectionGroup>
    </>
  );
}

function Row({ company, detail, children }: { company: Company; detail: ReactNode; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const fit = useQuery({ queryKey: ["fit"], queryFn: () => ok(client.GET("/api/reports/fit")) });
  const minFit = fit.data?.min_fit_score ?? 60;
  const person = company.summary?.contact_name;
  const qualification = qualificationOf(company);
  const failed = company.status === "failed";
  const hint =
    company.fit_score === null || company.fit_score === undefined
      ? null
      : company.fit_score < minFit
        ? { tone: "stopped" as const, text: `Fit ${company.fit_score} is below your minimum (${minFit}): probably not worth retrying` }
        : company.hot
          ? { tone: "attention" as const, text: "Hot lead: worth the retry" }
          : null;
  return (
    <li className="py-3.5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={company.name ?? company.domain} />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Link to="/leads/$companyId" params={{ companyId: company.id }} className="block truncate py-2.5 font-semibold text-ink hover:text-primary sm:py-0">
                {company.name ?? company.domain}
              </Link>
              {company.name && <Mono className="text-muted">{company.domain}</Mono>}
              {company.country_code && <Chip>{company.country_code}</Chip>}
              {company.hot && (
                <Chip tone="attention" title="A fit score above 80">
                  <Flame className="size-3.5" aria-hidden /> Hot
                </Chip>
              )}
            </div>
            <div className="mt-0.5 text-small text-muted">{detail}</div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-small text-muted">
              {person && (
                <span>
                  {person}
                  {company.summary?.contact_title ? `, ${company.summary.contact_title}` : ""}
                </span>
              )}
              {failed && (company.max_tries ?? 0) > 0 && <span>Try {Math.min(company.attempts ?? 0, company.max_tries ?? 0)} of {company.max_tries}</span>}
              {failed && company.failed_stage && <span>Stopped at {STEP_NAMES[company.failed_stage] ?? words(company.failed_stage)}</span>}
              <span>{company.source === "discovery" ? "Found by discovery" : company.source === "manual" ? "Added by you" : words(company.source)}</span>
              {company.summary && <span>{aiCredits(company.summary.credits_milli ?? 0)} used so far</span>}
            </div>
            {hint && <div className={cx("mt-1 text-small font-medium", hint.tone === "attention" ? "text-attention" : "text-ink-2")}>{hint.text}</div>}
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2">
          <FitRing score={company.fit_score} size={40} />
          {children}
          <Button variant="ghost" size="sm" aria-expanded={open} onClick={() => setOpen(!open)}>
            Details <ChevronDown className={cx("size-3.5 transition-transform", open && "rotate-180")} aria-hidden />
          </Button>
        </div>
      </div>
      {open && (
        <div className="mt-3 space-y-3 rounded-xl border border-line bg-surface-2 p-3 sm:ml-12">
          {company.fit_reason && (
            <p className="text-small text-ink-2">
              <span className="font-semibold">Why it fits: </span>
              {company.fit_reason}
            </p>
          )}
          {failed && company.last_error && (
            <p className="text-small text-ink-2">
              <span className="font-semibold">What went wrong: </span>
              {company.last_error}
            </p>
          )}
          {qualification ? <FitBreakdown data={qualification} compact /> : !company.fit_reason && <p className="text-small text-muted">No fit details were recorded for this lead.</p>}
        </div>
      )}
    </li>
  );
}

const openLead = (id: string) => (
  <Link to="/leads/$companyId" params={{ companyId: id }} className={buttonClass("secondary", "sm")}>
    Open <ArrowRight className="size-3.5" aria-hidden />
  </Link>
);

function FailedRow({ company }: { company: Company }) {
  const refresh = useRefresh();
  const retry = useMutation({ mutationFn: () => ok(client.POST("/api/companies/{company_id}/retry", { params: { path: { company_id: company.id } } })), onSuccess: refresh });
  return (
    <Row
      company={company}
      detail={
        <>
          <span className="text-error">{company.last_error ?? "failed"}</span>
          {company.next_action_at && <span> · automatic retry {new Date(company.next_action_at) > new Date() ? `at ${new Date(company.next_action_at).toLocaleTimeString()}` : "due"}</span>}
        </>
      }
    >
      <Button size="sm" busy={retry.isPending} onClick={() => retry.mutate()}>
        <RefreshCw className="size-3.5" aria-hidden /> Retry now
      </Button>
      {openLead(company.id)}
      <Problem error={retry.error} className="w-full" />
    </Row>
  );
}

function HeldRow({ company }: { company: Company }) {
  const refresh = useRefresh();
  const hold = describeHold(company.hold_reason ?? "");
  const suggestion = (company.research as { country_suggestion?: { code: string; evidence: string } | null } | null)?.country_suggestion;
  const path = { params: { path: { company_id: company.id } } };
  const setCountry = useMutation({
    mutationFn: async (code: string) => {
      await ok(client.PATCH("/api/companies/{company_id}", { ...path, body: { row_version: company.row_version, country_code: code } }));
      return ok(client.POST("/api/companies/{company_id}/release-hold", { ...path, body: {} }));
    },
    onSuccess: refresh,
  });
  const findAgain = useMutation({ mutationFn: () => ok(client.POST("/api/companies/find-email-again", { body: { company_ids: [company.id] } })), onSuccess: refresh });
  return (
    <Row company={company} detail={<>Held {ago(company.updated_at)}{suggestion && hold.action === "country" ? ` · probably ${suggestion.code}: ${suggestion.evidence}` : ""}</>}>
      {hold.action === "country" && suggestion && (
        <Button size="sm" busy={setCountry.isPending} onClick={() => setCountry.mutate(suggestion.code)}>
          <Globe2 className="size-3.5" aria-hidden /> Use {suggestion.code} and release
        </Button>
      )}
      {hold.action === "person" && (
        <Link to="/leads/$companyId" params={{ companyId: company.id }} hash="add-person" className={buttonClass("primary", "sm")}>
          <UserPlus className="size-3.5" aria-hidden /> Add a person with consent
        </Link>
      )}
      {hold.action === "wait" && (
        <span className="inline-flex items-center gap-1 text-small text-muted">
          <Clock className="size-3.5" aria-hidden /> Waiting for the resolver
        </span>
      )}
      {company.hold_reason === "catch_all_unverified" && (
        <Button size="sm" busy={findAgain.isPending} onClick={() => findAgain.mutate()} title="Search for this person's email again, with fresh vendor answers">
          <RefreshCw className="size-3.5" aria-hidden /> Find email again
        </Button>
      )}
      {openLead(company.id)}
      {findAgain.isSuccess && <span className="text-small text-good">Queued: it runs now</span>}
      <Problem error={setCountry.error ?? findAgain.error} className="w-full" />
    </Row>
  );
}

function CreditWait({ leads, rows, renews }: { leads: Company[]; rows: number; renews: string }) {
  const refresh = useRefresh();
  const all = useMutation({ mutationFn: () => ok(client.POST("/api/companies/resume")), onSuccess: refresh });
  const one = useMutation({ mutationFn: (id: string) => ok(client.POST("/api/companies/{company_id}/resume", { params: { path: { company_id: id } } })), onSuccess: refresh });
  return (
    <Section
      id="credits"
      tour="credit-wait"
      title="Waiting for AI credits"
      summary={`${leads.length + rows} paused where they are, losing nothing${renews ? ` · allowance renews ${renews}` : ""}`}
      chip={<Chip tone="attention">{leads.length + rows}</Chip>}
      actions={
        <Button size="sm" busy={all.isPending} onClick={() => all.mutate()}>
          Resume all now
        </Button>
      }
    >
      <p className="mb-3 text-small text-muted">Your plan's AI credits for this month ran out. They continue by themselves when credits are back; Resume tries now.</p>
      <Problem error={all.error ?? one.error} className="mb-3" />
      {rows > 0 && (
        <p className="mb-2 text-body text-ink-2">
          {rows} compan{rows === 1 ? "y" : "ies"} you added {rows === 1 ? "is" : "are"} waiting to become leads. See them under{" "}
          <Link to="/targets" className="font-semibold text-primary hover:underline">
            Add leads
          </Link>
          .
        </p>
      )}
      <ul className="divide-y divide-line">
        {leads.map((c) => (
          <Row key={c.id} company={c} detail={`Waiting for AI credits before: ${(STEP_LABEL[c.credit_wait_step ?? ""] ?? c.credit_wait_step ?? "").toLowerCase()}`}>
            <Button size="sm" variant="secondary" busy={one.isPending && one.variables === c.id} onClick={() => one.mutate(c.id)}>
              Resume
            </Button>
          </Row>
        ))}
      </ul>
    </Section>
  );
}

function BulkAction({ ids, kind, label }: { ids: string[]; kind: "retry" | "release"; label: string }) {
  const refresh = useRefresh();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const run = useMutation({
    mutationFn: () => {
      const body = { company_ids: ids.slice(0, 200) };
      return ok(kind === "retry" ? client.POST("/api/companies/retry", { body }) : client.POST("/api/companies/release-holds", { body }));
    },
    onSuccess: (data) => {
      setConfirming(false);
      refresh();
      toast({ tone: "good", title: `${data.retried} started`, body: data.skipped ? `${data.skipped} had already moved on.` : "They run now, in one run." });
    },
  });
  const n = ids.length;
  return (
    <>
      <Button size="sm" onClick={() => setConfirming(true)}>
        <RefreshCw className="size-3.5" aria-hidden /> {label} ({n})
      </Button>
      {confirming && (
        <Confirm title={kind === "retry" ? `Retry ${n} lead${n === 1 ? "" : "s"}?` : `Release ${n} lead${n === 1 ? "" : "s"}?`} confirm={kind === "retry" ? "Retry" : "Release"} busy={run.isPending} onClose={() => setConfirming(false)} onConfirm={() => run.mutate()}>
          <p>
            {kind === "retry"
              ? "Each lead goes back to the step that failed and runs again now, in one run. A step that calls vendors or the AI model (research, the email address, writing) uses AI credits again for every lead; anything already found is reused."
              : "Each lead goes back to looking for its email and writing it, in one run started now; the email will say you already wrote on LinkedIn."}
          </p>
          <Problem error={run.error} className="mt-3" />
        </Confirm>
      )}
    </>
  );
}

function FindAgainAll({ ids }: { ids: string[] }) {
  const refresh = useRefresh();
  const [confirming, setConfirming] = useState(false);
  const run = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/find-email-again", { body: { company_ids: ids.slice(0, 200) } })),
    onSuccess: () => {
      setConfirming(false);
      refresh();
    },
  });
  return (
    <>
      <Button size="sm" onClick={() => setConfirming(true)}>
        <RefreshCw className="size-3.5" aria-hidden /> Find again for all ({ids.length})
      </Button>
      {confirming && (
        <Confirm title={`Look for ${ids.length} email${ids.length === 1 ? "" : "s"} again?`} confirm="Find again" busy={run.isPending} onClose={() => setConfirming(false)} onConfirm={() => run.mutate()}>
          <p>Each lead is checked once more with fresh answers from the vendors. This uses AI credits for every lead. They run in one run, started now.</p>
          <Problem error={run.error} className="mt-3" />
        </Confirm>
      )}
    </>
  );
}

export function ConfirmRow({ row }: { row: Schemas["WaitingRowOut"] }) {
  const refresh = useRefresh();
  const [domain, setDomain] = useState("");
  const confirm = useMutation({
    mutationFn: () => ok(client.POST("/api/targets/{row_id}/confirm", { params: { path: { row_id: row.id } }, body: { domain: domain.trim() || row.resolved_domain || "" } })),
    onSuccess: refresh,
  });
  const typed = Object.entries(row.raw)
    .filter(([, v]) => v)
    .map(([k, v]) => `${words(k)}: ${String(v)}`)
    .join(" · ");
  return (
    <li className="flex flex-col gap-3 py-3.5 lg:flex-row lg:items-center lg:justify-between">
      <div className="min-w-0">
        <div className="font-semibold text-ink">{typed || "A row without details"}</div>
        <div className="mt-0.5 text-small text-muted">
          {row.resolved_domain ? (
            <>
              Best guess <Mono className="text-ink">{row.resolved_domain}</Mono>
              {row.resolution_confidence != null && `, ${Math.round(row.resolution_confidence * 100)}% sure`}
            </>
          ) : (
            "No website found"
          )}
          {row.reason && ` · ${row.reason}`}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input aria-label="Website for this row" placeholder={row.resolved_domain ? "Or type the right website" : "Company website"} value={domain} onChange={(e) => setDomain(e.target.value)} className="w-60" />
        <Button size="sm" busy={confirm.isPending} disabled={!(domain.trim() || row.resolved_domain)} onClick={() => confirm.mutate()}>
          {domain.trim() ? "Use this website" : row.resolved_domain ? `Yes, ${row.resolved_domain}` : "Confirm"}
        </Button>
      </div>
      <Problem error={confirm.error} className="w-full" />
    </li>
  );
}
