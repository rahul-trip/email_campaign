import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, GitFork, Plus, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Button, Card, Empty, PageHeader, Problem, Select, Skeleton, Table, Td, Th, buttonClass } from "../components/ui";
import { cx } from "../lib/cx";
import { ago, when } from "../lib/format";
import { HOLD_REASONS, LEAD_STATUSES, STAGES, describe, describeHold, leadStatus, stagesDone } from "../lib/status";

export type LeadsSearch = { q?: string; status?: string; hold?: string; page?: number };

const PAGE_SIZE = 25;
type Status = Schemas["CompanyOut"]["status"];
type Hold = NonNullable<Schemas["CompanyOut"]["hold_reason"]>;

export function LeadsPage() {
  const search = useSearch({ from: "/leads" });
  const navigate = useNavigate({ from: "/leads" });
  const page = search.page ?? 1;
  const set = (change: Partial<LeadsSearch>) => void navigate({ search: (prev) => ({ ...prev, page: undefined, ...change }), replace: true });

  // Type freely; the list follows a moment after typing stops.
  const [typed, setTyped] = useState(search.q ?? "");
  useEffect(() => setTyped(search.q ?? ""), [search.q]);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      if ((typed.trim() || undefined) !== search.q) set({ q: typed.trim() || undefined });
    }, 300);
    return () => window.clearTimeout(timer);
  });

  const leads = useQuery({
    queryKey: ["companies", search],
    queryFn: () =>
      ok(
        client.GET("/api/companies", {
          params: {
            query: {
              q: search.q,
              status: search.status as Status | undefined,
              hold_reason: search.hold as Hold | undefined,
              limit: PAGE_SIZE,
              offset: (page - 1) * PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: (previous) => previous,
    refetchInterval: 15000,
  });

  const total = leads.data?.total ?? 0;
  const items = leads.data?.items ?? [];
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Boolean(search.q || search.status || search.hold);

  return (
    <>
      <PageHeader
        title="Leads"
        subtitle={leads.isSuccess ? `${total} ${filtered ? "matching" : ""} compan${total === 1 ? "y" : "ies"}` : "Loading…"}
        actions={
          <Link to="/targets" className={buttonClass("primary")}>
            <Plus className="size-4" aria-hidden /> Add leads
          </Link>
        }
      />

      <Card tour="leads-list" className="p-0">
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <div className="relative min-w-[220px] max-w-sm flex-1">
            <Search className="absolute left-2.5 top-2 size-4 text-muted" aria-hidden />
            <input
              aria-label="Search by company or domain"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="Search by company or domain"
              className="h-8 w-full rounded-lg border border-outline bg-surface-low pl-8 pr-3 text-[13px] outline-none focus:border-primary-container focus:ring-2 focus:ring-primary-container/20"
            />
          </div>
          <Select aria-label="Status" value={search.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined, hold: e.target.value === "held" ? search.hold : undefined })} className="w-auto">
            <option value="">Any status</option>
            {LEAD_STATUSES.map((s) => (
              <option key={s} value={s}>
                {describe(leadStatus, s).label}
              </option>
            ))}
          </Select>
          <Select aria-label="Hold reason" value={search.hold ?? ""} onChange={(e) => set({ hold: e.target.value || undefined, status: e.target.value ? "held" : search.status })} className="w-auto">
            <option value="">Any hold reason</option>
            {HOLD_REASONS.map((h) => (
              <option key={h} value={h}>
                {describeHold(h).label}
              </option>
            ))}
          </Select>
          {filtered && (
            <Button variant="ghost" size="sm" onClick={() => set({ q: undefined, status: undefined, hold: undefined })}>
              <X className="size-3.5" aria-hidden /> Clear filters
            </Button>
          )}
        </div>

        <Problem error={leads.error} className="m-3" />
        {leads.isPending ? (
          <div className="p-4">
            <Skeleton rows={6} />
          </div>
        ) : items.length === 0 ? (
          <Empty
            title={filtered ? "No lead matches" : "No leads yet"}
            action={
              filtered ? undefined : (
                <Link to="/targets" className={buttonClass("primary")}>
                  Add your first target
                </Link>
              )
            }
          >
            {filtered ? "Try another search or clear the filters." : "Add a company by website, name, email or LinkedIn profile, then start a run."}
          </Empty>
        ) : (
          <Table>
            <thead>
              <tr>
                <Th>Company</Th>
                <Th>Status</Th>
                <Th className="hidden lg:table-cell">Stage</Th>
                <Th className="text-center">Country</Th>
                <Th className="text-center">Fit</Th>
                <Th className="hidden text-center md:table-cell">Priority</Th>
                <Th className="hidden xl:table-cell">Added</Th>
                <Th className="hidden xl:table-cell">Last change</Th>
                <Th>
                  <span className="sr-only">Links</span>
                </Th>
              </tr>
            </thead>
            <tbody className={cx(leads.isFetching && leads.isPlaceholderData && "opacity-60")}>
              {items.map((company, row) => {
                const hold = company.hold_reason ? describeHold(company.hold_reason) : null;
                return (
                  <tr key={company.id} className="hover:bg-surface-low">
                    <Td>
                      <Link to="/leads/$companyId" params={{ companyId: company.id }} className="font-semibold hover:text-primary hover:underline">
                        {company.name ?? company.domain}
                      </Link>
                      <div className="font-mono text-[11px] text-muted">{company.domain}</div>
                    </Td>
                    <Td>
                      <StatusBadge status={describe(leadStatus, company.status)} />
                      {hold && <div className="mt-1 text-[11px] text-attention">{hold.label}</div>}
                      {company.status === "failed" && company.last_error && (
                        <div className="mt-1 max-w-[16rem] truncate text-[11px] text-error" title={company.last_error}>
                          {company.last_error}
                        </div>
                      )}
                    </Td>
                    <Td className="hidden lg:table-cell">
                      <StageBar done={stagesDone(company.status)} />
                    </Td>
                    <Td className="text-center font-mono text-xs text-muted">{company.country_code ?? "–"}</Td>
                    <Td className="text-center">
                      {company.fit_score != null ? (
                        <span className={cx("rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold", company.fit_score >= 70 ? "bg-good-container text-on-good-container" : "bg-surface-container text-muted")}>
                          {company.fit_score}
                        </span>
                      ) : (
                        <span className="text-muted">–</span>
                      )}
                    </Td>
                    <Td className="hidden text-center font-mono text-xs md:table-cell">{company.priority}</Td>
                    <Td className="hidden whitespace-nowrap text-xs text-muted xl:table-cell">
                      <span title={when(company.created_at)}>{ago(company.created_at)}</span>
                    </Td>
                    <Td className="hidden whitespace-nowrap text-xs text-muted xl:table-cell">
                      <span title={when(company.updated_at)}>{ago(company.updated_at ?? company.created_at)}</span>
                    </Td>
                    <Td className="text-right">
                      <Link to="/leads/$companyId/journey" params={{ companyId: company.id }} data-tour={row === 0 ? "leads-journey" : undefined} className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
                        <GitFork className="size-3" aria-hidden /> Journey
                      </Link>
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}

        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-line p-3 text-xs text-muted">
            <span>
              {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => void navigate({ search: (prev) => ({ ...prev, page: page - 1 > 1 ? page - 1 : undefined }) })}>
                <ChevronLeft className="size-3.5" aria-hidden /> Previous
              </Button>
              <span className="font-mono">
                {page} / {pages}
              </span>
              <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => void navigate({ search: (prev) => ({ ...prev, page: page + 1 }) })}>
                Next <ChevronRight className="size-3.5" aria-hidden />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </>
  );
}

/** Eight small segments: how far along the main path a lead is. Off-path leads show none. */
export function StageBar({ done }: { done: number | null }) {
  if (done === null) return <span className="text-[11px] text-muted">off the main path</span>;
  return (
    <div className="flex items-center gap-2" aria-label={`${done} of ${STAGES.length} stages done`} title={done < STAGES.length ? `Next: ${STAGES[done]}` : "All stages done"}>
      <div className="flex gap-0.5" aria-hidden>
        {STAGES.map((stage, i) => (
          <span key={stage} className={cx("h-1.5 w-3 rounded-sm", i < done ? "bg-good" : i === done ? "bg-working" : "bg-surface-container")} />
        ))}
      </div>
      <span className="text-[11px] text-muted">{done < STAGES.length ? STAGES[done] : "Done"}</span>
    </div>
  );
}
