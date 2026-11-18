/**
 * Leads: saved views, filter pills, a clickable stage ribbon and a readable table. Every filter
 * lives in the URL so a view can be bookmarked or shared. Uses the list's server-side filters
 * (status, hold, search, fit, hot, source, country, sort) and the per-row summary (contact,
 * email status, spend).
 */
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight, Flame, GitFork, Plus, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import type { LeadsSearch } from "../router";
import { cx } from "../lib/cx";
import { ago, usd, when } from "../lib/format";
import { HOLD_REASONS, LEAD_STATUSES, STAGES, describe, describeHold, emailStatus, leadStatus, stagesDone } from "../lib/status";
import { Avatar, Button, buttonClass, Card, Chip, Empty, Mono, PageHeader, Problem, Select, Skeleton } from "../ui/core";
import { FitRing } from "../ui/viz";

const PAGE_SIZE = 25;
type Status = Schemas["CompanyOut"]["status"];
type Hold = NonNullable<Schemas["CompanyOut"]["hold_reason"]>;
type Source = "discovery" | "manual" | "import" | "referral";

/** Saved views: each is a set of filters, so the view and the URL always agree. */
const VIEWS: { key: string; label: string; filters: Partial<LeadsSearch> }[] = [
  { key: "all", label: "All", filters: {} },
  { key: "hot", label: "Hot", filters: { view: "hot", sort: "fit" } },
  { key: "review", label: "Waiting review", filters: { status: "copy_ready" } },
  { key: "approved", label: "Approved", filters: { status: "approved" } },
  { key: "held", label: "On hold", filters: { status: "held" } },
  { key: "failed", label: "Failed", filters: { status: "failed" } },
  { key: "disqualified", label: "Disqualified", filters: { status: "disqualified" } },
];
const RIBBON = ["new", "researched", "qualified", "contacts_found", "email_ready", "copy_ready", "approved", "in_sequence", "replied"];
const SOURCES: [Source, string][] = [
  ["discovery", "Discovery"],
  ["manual", "Added by you"],
  ["import", "Uploaded"],
  ["referral", "Referral"],
];

export function LeadsPage() {
  const search = useSearch({ from: "/leads" });
  const navigate = useNavigate({ from: "/leads" });
  const page = search.page ?? 1;
  const set = (change: Partial<LeadsSearch>) => void navigate({ search: (prev) => ({ ...prev, page: undefined, ...change }), replace: true });

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
              hot: search.view === "hot" ? true : undefined,
              source: search.source as Source | undefined,
              country: search.country,
              min_fit: search.fit,
              sort: (search.sort as "newest" | "fit" | "updated" | "name" | undefined) ?? "newest",
              include: "summary",
              limit: PAGE_SIZE,
              offset: (page - 1) * PAGE_SIZE,
            },
          },
        }),
      ),
    placeholderData: (previous) => previous,
    refetchInterval: 15000,
  });
  const status = useQuery({ queryKey: ["status"], queryFn: () => ok(client.GET("/api/status")), refetchInterval: 10000 });

  const total = leads.data?.total ?? 0;
  const items = leads.data?.items ?? [];
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const advancedCount = [search.hold, search.source, search.fit, search.country].filter(Boolean).length;
  const [moreOpen, setMore] = useState(advancedCount > 0);
  const filtered = Boolean(search.q || search.status || search.hold || search.view || search.source || search.country || search.fit);
  const activeView = VIEWS.find((v) => Object.entries(v.filters).every(([k, val]) => search[k as keyof LeadsSearch] === val) && (v.key !== "all" || !filtered))?.key;
  const by = status.data?.by_status ?? {};
  const ribbonTotal = RIBBON.reduce((a, s) => a + (by[s] ?? 0), 0);

  return (
    <>
      <PageHeader
        title="Leads"
        subtitle={leads.isSuccess ? `${total.toLocaleString()} ${filtered ? "matching " : ""}compan${total === 1 ? "y" : "ies"}` : "Loading…"}
        actions={
          <Link to="/targets" className={buttonClass("primary")}>
            <Plus className="size-4" aria-hidden /> Add leads
          </Link>
        }
      />

      {/* Saved views */}
      <div className="mb-4 flex flex-wrap gap-2" role="tablist" aria-label="Views">
        {VIEWS.map((v) => (
          <button
            key={v.key}
            type="button"
            role="tab"
            aria-selected={activeView === v.key}
            onClick={() => void navigate({ search: { ...v.filters }, replace: true })}
            className={cx("press inline-flex h-9 items-center gap-1.5 rounded-full border px-4 text-small font-semibold", activeView === v.key ? "border-primary bg-primary-soft text-primary" : "border-line-strong bg-surface text-ink-2 hover:text-ink")}
          >
            {v.key === "hot" && <Flame className="size-3.5" aria-hidden />}
            {v.label}
            {v.filters.status && <span className="tnum text-muted">{by[v.filters.status] ?? 0}</span>}
          </button>
        ))}
      </div>

      {/* Stage ribbon: each segment's width is how many leads sit there; click to filter. */}
      {ribbonTotal > 0 && (
        <div className="mb-4 flex h-3 overflow-hidden rounded-full bg-surface-3" aria-label="Leads by stage">
          {RIBBON.filter((s) => by[s]).map((s) => (
            <button
              key={s}
              type="button"
              title={`${describe(leadStatus, s).label}: ${by[s]}`}
              onClick={() => set({ status: s, view: undefined })}
              className={cx("h-full transition-opacity hover:opacity-80", search.status === s && "ring-2 ring-ink ring-inset")}
              style={{ width: `${((by[s] ?? 0) / ribbonTotal) * 100}%`, background: `var(--${describe(leadStatus, s).family}-dot)` }}
            />
          ))}
        </div>
      )}

      <Card data-tour="leads-list" className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-line bg-surface-2 p-3">
          <div className="relative max-w-sm min-w-[220px] flex-1">
            <Search className="absolute top-3 left-3 size-4 text-faint" aria-hidden />
            <input
              aria-label="Search by company or domain"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="Search by company or website"
              className="h-10 w-full rounded-[var(--radius-control)] border border-line-strong bg-surface pr-3 pl-9 text-body text-ink outline-none focus:border-primary focus:shadow-[0_0_0_3px_var(--primary-soft)]"
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
          <Button variant="secondary" aria-expanded={moreOpen} onClick={() => setMore(!moreOpen)} className="h-10">
            <SlidersHorizontal className="size-4" aria-hidden /> Filters
            {advancedCount > 0 && <span className="tnum rounded-full bg-primary px-1.5 text-label text-primary-ink">{advancedCount}</span>}
          </Button>
          <Select aria-label="Sort" value={search.sort ?? "newest"} onChange={(e) => set({ sort: e.target.value === "newest" ? undefined : e.target.value })} className="ml-auto w-auto">
            <option value="newest">Newest first</option>
            <option value="fit">Best fit first</option>
            <option value="updated">Recently changed</option>
            <option value="name">Name A–Z</option>
          </Select>
          {filtered && (
            <Button variant="ghost" size="sm" onClick={() => void navigate({ search: {}, replace: true })}>
              <X className="size-3.5" aria-hidden /> Clear
            </Button>
          )}
          {moreOpen && <div className="flex basis-full flex-wrap items-center gap-2 border-t border-line pt-3">
          <Select aria-label="Hold reason" value={search.hold ?? ""} onChange={(e) => set({ hold: e.target.value || undefined, status: e.target.value ? "held" : search.status })} className="w-auto">
            <option value="">Any hold</option>
            {HOLD_REASONS.map((h) => (
              <option key={h} value={h}>
                {describeHold(h).label}
              </option>
            ))}
          </Select>
          <Select aria-label="Source" value={search.source ?? ""} onChange={(e) => set({ source: e.target.value || undefined })} className="w-auto">
            <option value="">Any source</option>
            {SOURCES.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </Select>
          <Select aria-label="Minimum fit" value={search.fit ?? ""} onChange={(e) => set({ fit: e.target.value ? Number(e.target.value) : undefined })} className="w-auto">
            <option value="">Any fit</option>
            {[60, 70, 80, 90].map((n) => (
              <option key={n} value={n}>
                Fit {n}+
              </option>
            ))}
          </Select>
          <input
            aria-label="Country code"
            value={search.country ?? ""}
            maxLength={2}
            placeholder="Country"
            onChange={(e) => set({ country: e.target.value.length === 2 ? e.target.value.toUpperCase() : undefined })}
            className="h-10 w-24 rounded-[var(--radius-control)] border border-line-strong bg-surface px-3 text-body uppercase outline-none focus:border-primary"
          />
          </div>}
        </div>

        <Problem error={leads.error} className="m-3" />
        {leads.isPending ? (
          <div className="p-5">
            <Skeleton rows={8} shape="table" />
          </div>
        ) : items.length === 0 ? (
          <Empty
            title={filtered ? "No lead matches" : "No leads yet"}
            action={
              filtered ? undefined : (
                <Link to="/targets" className={buttonClass("primary")}>
                  Add your first lead
                </Link>
              )
            }
          >
            {filtered ? "Try another search or clear the filters." : "Add a company by website, name, email or LinkedIn profile, or let discovery find some."}
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-label font-semibold tracking-wide text-faint uppercase">
                <tr className="border-b border-line">
                  <th className="px-4 py-3">Company</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="hidden px-3 py-3 lg:table-cell">Stage</th>
                  <th className="px-3 py-3 text-center">Fit</th>
                  <th className="hidden px-3 py-3 md:table-cell">Contact</th>
                  <th className="hidden px-3 py-3 xl:table-cell">Email</th>
                  <th className="hidden px-3 py-3 text-right xl:table-cell">Spend</th>
                  <th className="hidden px-3 py-3 xl:table-cell">Changed</th>
                  <th className="px-4 py-3">
                    <span className="sr-only">Links</span>
                  </th>
                </tr>
              </thead>
              <tbody className={cx("divide-y divide-line", leads.isFetching && leads.isPlaceholderData && "opacity-60")}>
                {items.map((company, row) => {
                  const hold = company.hold_reason ? describeHold(company.hold_reason) : null;
                  const info = describe(leadStatus, company.status);
                  const s = company.summary;
                  return (
                    <tr key={company.id} className="group transition-colors hover:bg-surface-2">
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-3">
                          <Avatar name={company.name ?? company.domain} />
                          <div className="min-w-0">
                            <Link to="/leads/$companyId" params={{ companyId: company.id }} className="font-semibold text-ink hover:text-primary">
                              {company.name ?? company.domain}
                            </Link>
                            <div className="flex items-center gap-1.5 text-small text-muted">
                              <Mono>{company.domain}</Mono>
                              {company.country_code && <span>· {company.country_code}</span>}
                              {company.priority !== 5 && <span title="Priority (1 is first)">· P{company.priority}</span>}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3.5">
                        <Chip tone={info.family}>{info.label}</Chip>
                        {hold && <div className="mt-1 text-small text-attention">{hold.label}</div>}
                        {company.status === "failed" && company.last_error && (
                          <div className="mt-1 max-w-[16rem] truncate text-small text-error" title={company.last_error}>
                            {company.last_error}
                          </div>
                        )}
                      </td>
                      <td className="hidden px-3 py-3.5 lg:table-cell">
                        <StageBar done={stagesDone(company.status)} />
                      </td>
                      <td className="px-3 py-3.5">
                        <div className="flex justify-center">
                          <FitRing score={company.fit_score} />
                        </div>
                      </td>
                      <td className="hidden px-3 py-3.5 md:table-cell">
                        {s?.contact_name ? (
                          <>
                            <div className="text-body text-ink">{s.contact_name}</div>
                            <div className="max-w-[14rem] truncate text-small text-muted">{s.contact_title}</div>
                          </>
                        ) : (
                          <span className="text-small text-faint">Not found yet</span>
                        )}
                      </td>
                      <td className="hidden px-3 py-3.5 xl:table-cell">{s?.email_status ? <Chip tone={describe(emailStatus, s.email_status).family}>{describe(emailStatus, s.email_status).label}</Chip> : <span className="text-small text-faint">—</span>}</td>
                      <td className="tnum hidden px-3 py-3.5 text-right text-small text-ink-2 xl:table-cell">{s ? usd(s.cost_micro_usd) : "—"}</td>
                      <td className="hidden px-3 py-3.5 text-small whitespace-nowrap text-muted xl:table-cell">
                        <span title={`Added ${when(company.created_at)}`}>{ago(company.updated_at ?? company.created_at)}</span>
                      </td>
                      <td className="px-4 py-3.5 text-right">
                        <Link
                          to="/leads/$companyId"
                          params={{ companyId: company.id }}
                          search={{ tab: "journey" }}
                          data-tour={row === 0 ? "leads-journey" : undefined}
                          className="inline-flex items-center gap-1 text-small font-semibold text-primary opacity-70 group-hover:opacity-100 hover:underline"
                        >
                          <GitFork className="size-3.5" aria-hidden /> Journey
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}

        {total > PAGE_SIZE && (
          <div className="flex items-center justify-between border-t border-line p-3 text-small text-muted">
            <span className="tnum">
              {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total.toLocaleString()}
            </span>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => void navigate({ search: (prev) => ({ ...prev, page: page - 1 > 1 ? page - 1 : undefined }) })}>
                <ChevronLeft className="size-4" aria-hidden /> Previous
              </Button>
              <span className="tnum">
                {page} / {pages}
              </span>
              <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => void navigate({ search: (prev) => ({ ...prev, page: page + 1 }) })}>
                Next <ChevronRight className="size-4" aria-hidden />
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
  if (done === null) return <span className="text-small text-faint">off the main path</span>;
  return (
    <div className="flex items-center gap-2" aria-label={`${done} of ${STAGES.length} stages done`} title={done < STAGES.length ? `Next: ${STAGES[done]}` : "All stages done"}>
      <div className="flex gap-0.5" aria-hidden>
        {STAGES.map((stage, i) => (
          <span key={stage} className={cx("h-1.5 w-3 rounded-full", i < done ? "bg-good-dot" : i === done ? "bg-working-dot" : "bg-surface-3")} />
        ))}
      </div>
      <span className="text-small text-muted">{done < STAGES.length ? STAGES[done] : "Done"}</span>
    </div>
  );
}
