/**
 * Needs attention: everything waiting on a person except email review. Tabs with counts; each
 * group is a folding section (the first open) with its plain cause, its fix and a bulk action.
 * Same actions as web2: retry one, by step or all; release; find email again (one or all);
 * use the suggested country and release; resume after a credit wait; confirm websites.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, CheckCircle2, Clock, Globe2, RefreshCw, UserPlus } from "lucide-react";
import { useState, type ReactNode } from "react";
import { client, ok, type Schemas } from "../api/client";
import { ago, words } from "../lib/format";
import { HOLD_REASONS, describeHold } from "../lib/status";
import { STEP_LABEL, day, useUsage } from "../lib/usage";
import { Avatar, Button, buttonClass, Card, Chip, Empty, Input, Mono, PageHeader, Problem, Skeleton } from "../ui/core";
import { Confirm, Tabs, useToast } from "../ui/overlay";
import { Section, SectionGroup } from "../ui/sections";

type Company = Schemas["CompanyOut"];
type Filter = "all" | "held" | "failed" | "confirm" | "credits";

const STEP_ORDER = ["research", "gate", "contacts", "email", "copy", "deliver"];
const STEP_NAMES: Record<string, string> = { research: "research", gate: "qualification", contacts: "people", email: "the email address", copy: "writing the email", deliver: "the mailbox", other: "another step" };

function useRefresh() {
  const queryClient = useQueryClient();
  return () => ["companies", "status", "lead", "journey", "waiting", "usage"].forEach((key) => void queryClient.invalidateQueries({ queryKey: [key] }));
}

export function AttentionPage() {
  const [filter, setFilter] = useState<Filter>("all");
  const lists = useQuery({
    queryKey: ["companies", "attention"],
    queryFn: async () => {
      const [held, failed] = await Promise.all([
        ok(client.GET("/api/companies", { params: { query: { status: "held", limit: 200 } } })),
        ok(client.GET("/api/companies", { params: { query: { status: "failed", limit: 200 } } })),
      ]);
      return { held: held.items, failed: failed.items };
    },
    refetchInterval: 10000,
  });
  const waiting = useQuery({ queryKey: ["waiting"], queryFn: () => ok(client.GET("/api/targets/waiting")) });
  const usage = useUsage();
  const credits = useQuery({ queryKey: ["companies", "credits"], queryFn: () => ok(client.GET("/api/companies", { params: { query: { waiting_for_credits: true, limit: 200 } } })), refetchInterval: 10000 });

  const held = lists.data?.held ?? [];
  const failed = lists.data?.failed ?? [];
  const confirm = waiting.data ?? [];
  const parked = credits.data?.items ?? [];
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
        title="Needs attention"
        subtitle={total ? `${total} item${total === 1 ? "" : "s"} wait on you. Most take one click.` : "Holds, failures, websites to confirm and credit waits land here."}
        actions={
          filter !== "credits" &&
          failed.length > 1 &&
          byStage.length > 1 && (
            <span data-tour="attention-retry-all">
              <BulkAction ids={failed.map((c) => c.id)} kind="retry" label="Retry every failed lead" />
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
            { key: "failed", label: "Failed", count: failed.length },
            { key: "held", label: "On hold", count: held.length },
            { key: "confirm", label: "Websites to confirm", count: confirm.length },
            { key: "credits", label: "Waiting for credits", count: parked.length + rows },
          ]}
        />
      </div>

      {loading && <Skeleton rows={6} />}
      <Problem error={lists.error ?? waiting.error} />
      {!loading && total === 0 && (
        <Card>
          <Empty art={<CheckCircle2 className="size-12 text-good-dot" />} title="All clear — nothing waits on you ✨">
            Held leads, failures and websites to confirm appear here the moment they happen.
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
              title={`Failed at ${STEP_NAMES[stage] ?? words(stage)}`}
              summary={`${list.length} lead${list.length === 1 ? "" : "s"} · ${list[0]?.last_error ?? "a step failed"}`}
              chip={<Chip tone="error">{list.length} failed</Chip>}
              actions={<BulkAction ids={list.map((c) => c.id)} kind="retry" label="Retry all" />}
            >
              <p className="mb-3 text-small text-muted">A step failed. Each lead retries itself up to 3 times, waiting longer each time; you can retry at once.</p>
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
  return (
    <li className="flex flex-col gap-3 py-3.5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 items-center gap-3">
        <Avatar name={company.name ?? company.domain} />
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Link to="/leads/$companyId" params={{ companyId: company.id }} className="truncate font-semibold text-ink hover:text-primary">
              {company.name ?? company.domain}
            </Link>
            <Mono className="text-muted">{company.domain}</Mono>
            {company.country_code && <Chip>{company.country_code}</Chip>}
          </div>
          <div className="mt-0.5 text-small text-muted">{detail}</div>
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div>
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
      title="Waiting for credits"
      summary={`${leads.length + rows} paused where they are, losing nothing${renews ? ` · allowance renews ${renews}` : ""}`}
      chip={<Chip tone="attention">{leads.length + rows}</Chip>}
      actions={
        <Button size="sm" busy={all.isPending} onClick={() => all.mutate()}>
          Resume all now
        </Button>
      }
    >
      <p className="mb-3 text-small text-muted">Your plan's allowance for a step ran out. They continue by themselves when credits exist; Resume tries now.</p>
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
          <Row key={c.id} company={c} detail={`Waiting for a credit: ${(STEP_LABEL[c.credit_wait_step ?? ""] ?? c.credit_wait_step ?? "").toLowerCase()}`}>
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
              ? "Each lead goes back to the step that failed and runs again now, in one run. A step that pays vendors (research, the email address, writing) costs again for every lead; anything already found is reused."
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
          <p>Each lead is checked once more with fresh answers from the vendors. This costs vendor credits for every lead. They run in one run, started now.</p>
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
