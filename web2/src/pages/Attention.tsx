import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowRight, CheckCircle2, Clock, Globe2, RefreshCw, UserPlus } from "lucide-react";
import { useState, type ReactNode } from "react";
import { client, ok, type Schemas } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Button, Card, Empty, Input, PageHeader, Problem, Segmented, Skeleton, buttonClass } from "../components/ui";
import { ago, words } from "../lib/format";
import { HOLD_REASONS, describe, describeHold, leadStatus } from "../lib/status";

type Company = Schemas["CompanyOut"];
type Filter = "all" | "held" | "failed" | "confirm";

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

  const held = lists.data?.held ?? [];
  const failed = lists.data?.failed ?? [];
  const confirm = waiting.data ?? [];
  const total = held.length + failed.length + confirm.length;
  const groups = HOLD_REASONS.map((reason) => [reason, held.filter((c) => c.hold_reason === reason)] as const).filter(([, rows]) => rows.length > 0);
  const show = (kind: Filter) => filter === "all" || filter === kind;

  return (
    <>
      <PageHeader title="Needs attention" subtitle="Everything waiting on you except email review: holds, failures and websites to confirm." />

      <div className="mb-5" data-tour="attention-filter">
        <Segmented
          label="Show"
          value={filter}
          onChange={setFilter}
          options={[
            ["all", `All (${total})`],
            ["held", `On hold (${held.length})`],
            ["failed", `Failed (${failed.length})`],
            ["confirm", `Websites to confirm (${confirm.length})`],
          ]}
        />
      </div>

      {(lists.isPending || waiting.isPending) && <Skeleton rows={5} />}
      <Problem error={lists.error ?? waiting.error} />

      {lists.isSuccess && waiting.isSuccess && total === 0 && (
        <Card>
          <Empty icon={<CheckCircle2 className="size-8 text-good" />} title="Nothing needs you">
            Held leads, failures and websites to confirm appear here.
          </Empty>
        </Card>
      )}

      <div className="space-y-5">
        {show("held") &&
          groups.map(([reason, rows]) => {
            const hold = describeHold(reason);
            return (
              <Group key={reason} title={hold.label} count={rows.length} explain={`${hold.why} ${hold.fix}`}>
                {rows.map((company) => (
                  <HeldRow key={company.id} company={company} />
                ))}
              </Group>
            );
          })}

        {show("failed") && failed.length > 0 && (
          <Group title="Failed" count={failed.length} explain="A step failed. The lead retries itself up to 3 times, waiting longer each time; you can retry at once.">
            {failed.map((company) => (
              <FailedRow key={company.id} company={company} />
            ))}
          </Group>
        )}

        {show("confirm") && confirm.length > 0 && (
          <Group title="Websites to confirm" count={confirm.length} explain="These were added by name, and the website found is not certain. Confirm it, or give the right one.">
            {confirm.map((row) => (
              <ConfirmRow key={row.id} row={row} />
            ))}
          </Group>
        )}
      </div>
    </>
  );
}

function Group({ title, count, explain, children }: { title: string; count: number; explain: string; children: ReactNode }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          {title}
          <span className="rounded-full bg-surface-container px-2 font-mono text-xs">{count}</span>
        </span>
      }
      subtitle={explain}
    >
      <ul className="divide-y divide-line">{children}</ul>
    </Card>
  );
}

function Row({ company, detail, children }: { company: Company; detail: ReactNode; children: ReactNode }) {
  return (
    <li className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/leads/$companyId" params={{ companyId: company.id }} className="truncate font-semibold hover:text-primary hover:underline">
            {company.name ?? company.domain}
          </Link>
          <span className="font-mono text-[11px] text-muted">{company.domain}</span>
          {company.country_code && <span className="rounded bg-surface-container px-1.5 font-mono text-[10px]">{company.country_code}</span>}
        </div>
        <div className="mt-0.5 text-xs text-muted">{detail}</div>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">{children}</div>
    </li>
  );
}

function useRefresh() {
  const queryClient = useQueryClient();
  return () => {
    for (const key of ["companies", "status", "lead", "journey", "waiting"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
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
  const open = (
    <Link to="/leads/$companyId" params={{ companyId: company.id }} className={buttonClass("secondary", "sm")}>
      Open lead <ArrowRight className="size-3" aria-hidden />
    </Link>
  );
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
        <span className="inline-flex items-center gap-1 text-xs text-muted">
          <Clock className="size-3.5" aria-hidden /> Waiting for the resolver
        </span>
      )}
      {open}
      {setCountry.error != null && <Problem error={setCountry.error} className="w-full" />}
    </Row>
  );
}

function FailedRow({ company }: { company: Company }) {
  const refresh = useRefresh();
  const retry = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/retry", { params: { path: { company_id: company.id } } })),
    onSuccess: refresh,
  });
  return (
    <Row
      company={company}
      detail={
        <span className="text-error">
          {company.failed_stage ? `${words(company.failed_stage)} step: ` : ""}
          {company.last_error ?? "failed"}
          {company.next_action_at && <span className="text-muted"> · automatic retry {new Date(company.next_action_at) > new Date() ? `at ${new Date(company.next_action_at).toLocaleTimeString()}` : "due"}</span>}
        </span>
      }
    >
      <StatusBadge status={describe(leadStatus, "failed")} />
      <Button size="sm" busy={retry.isPending} onClick={() => retry.mutate()}>
        <RefreshCw className="size-3.5" aria-hidden /> Retry now
      </Button>
      <Link to="/leads/$companyId" params={{ companyId: company.id }} className={buttonClass("secondary", "sm")}>
        Open lead <ArrowRight className="size-3" aria-hidden />
      </Link>
      {retry.error != null && <Problem error={retry.error} className="w-full" />}
    </Row>
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
    .filter(([, value]) => value)
    .map(([key, value]) => `${words(key)}: ${String(value)}`)
    .join(" · ");
  return (
    <li className="flex flex-col gap-2 py-3 lg:flex-row lg:items-center lg:justify-between">
      <div className="min-w-0">
        <div className="font-semibold">{typed || "A row without details"}</div>
        <div className="mt-0.5 text-xs text-muted">
          {row.resolved_domain ? (
            <>
              Best guess <span className="font-mono text-ink">{row.resolved_domain}</span>
              {row.resolution_confidence != null && `, ${Math.round(row.resolution_confidence * 100)}% sure`}
            </>
          ) : (
            "No website found"
          )}
          {row.reason && ` · ${row.reason}`}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Input aria-label="Website for this row" placeholder={row.resolved_domain ? "Or type the right website" : "Company website"} value={domain} onChange={(e) => setDomain(e.target.value)} className="w-56" />
        <Button size="sm" busy={confirm.isPending} disabled={!(domain.trim() || row.resolved_domain)} onClick={() => confirm.mutate()}>
          {domain.trim() ? "Use this website" : row.resolved_domain ? `Yes, ${row.resolved_domain}` : "Confirm"}
        </Button>
      </div>
      {confirm.error != null && <Problem error={confirm.error} className="w-full" />}
    </li>
  );
}
