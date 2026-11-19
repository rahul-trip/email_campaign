/**
 * Leads: saved views, filter pills, a clickable stage ribbon and a readable table. Every filter
 * lives in the URL so a view can be bookmarked or shared. Uses the list's server-side filters
 * (status, hold, search, fit, hot, source, country, sort) and the per-row summary (contact,
 * email status, AI credits used).
 */
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, Flame, GitFork, Plus, Search, SlidersHorizontal, X } from "lucide-react";
import { useEffect, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import type { LeadsSearch } from "../router";
import { cx } from "../lib/cx";
import { ago, credits, plainError, when } from "../lib/format";
import { HOLD_REASONS, LEAD_STATUSES, STAGES, companyStatus, describe, describeHold, emailStatus, leadStatus, stagesDone } from "../lib/status";
import { Button, buttonClass, Card, Chip, Empty, Mono, PageHeader, Problem, Select, Skeleton } from "../ui/core";
import { LeadIcon } from "../ui/lead";
import { FitRing } from "../ui/viz";

const PAGE_SIZE = 25;
type Status = Schemas["CompanyOut"]["status"];
type Bucket = Schemas["CompanyOut"]["bucket"];
type Hold = NonNullable<Schemas["CompanyOut"]["hold_reason"]>;
type Source = "discovery" | "manual" | "import" | "referral";

/** Saved views: each is a set of filters, so the view and the URL always agree. */
const VIEWS: { key: string; label: string; filters: Partial<LeadsSearch>; count?: string }[] = [
  { key: "ready", label: "Ready for you", filters: { bucket: "ready" }, count: "ready" },
  { key: "hot", label: "Hot", filters: { view: "hot", sort: "fit" } },
  { key: "working", label: "Working on it", filters: { bucket: "working" }, count: "working" },
  { key: "decision", label: "Failed leads", filters: { bucket: "decision" }, count: "decision" },
  { key: "done", label: "Approved & sent", filters: { bucket: "done" }, count: "done" },
  { key: "screened", label: "Screened out", filters: { bucket: "screened_out" }, count: "screened_out" },
  { key: "all", label: "All", filters: {} },
];
type SortKey = "newest" | "fit" | "updated" | "name" | "status" | "country" | "source" | "priority";
/** Each sortable column and the direction it starts in (the server's natural order). */
const SORTS: [SortKey, string, "asc" | "desc"][] = [
  ["newest", "Date added", "desc"],
  ["updated", "Last changed", "desc"],
  ["fit", "Fit score", "desc"],
  ["name", "Name", "asc"],
  ["status", "Status", "asc"],
  ["country", "Country", "asc"],
  ["source", "Source", "asc"],
  ["priority", "Priority", "asc"],
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
              bucket: search.bucket as Bucket | undefined,
              source: search.source as Source | undefined,
              country: search.country,
              min_fit: search.fit,
              sort: (search.sort as SortKey | undefined) ?? "newest",
              direction: search.dir,
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
  const filtered = Boolean(search.q || search.bucket || search.status || search.hold || search.view || search.source || search.country || search.fit);
  const activeView = VIEWS.find((v) => Object.entries(v.filters).every(([k, val]) => search[k as keyof LeadsSearch] === val) && (v.key !== "all" || !filtered))?.key;
  const by = status.data?.by_status ?? {};
  const sortNow = (search.sort as SortKey | undefined) ?? "newest";
  const dirNow = search.dir ?? SORTS.find(([key]) => key === sortNow)![2];
  /** A column header that sorts by it; pressed again, it reverses. */
  const SortHead = ({ by: key, children, className }: { by: SortKey; children: string; className?: string }) => {
    const active = sortNow === key;
    const Icon = !active ? ArrowUpDown : dirNow === "asc" ? ArrowUp : ArrowDown;
    return (
      <th className={className} aria-sort={active ? (dirNow === "asc" ? "ascending" : "descending") : "none"}>
        <button
          type="button"
          onClick={() => set({ sort: key === "newest" ? undefined : key, dir: active ? (dirNow === "asc" ? "desc" : "asc") : undefined })}
          className={cx("inline-flex items-center gap-1 uppercase hover:text-ink", active && "text-ink")}
        >
          {children}
          <Icon className={cx("size-3", !active && "opacity-50")} aria-hidden />
        </button>
      </th>
    );
  };
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
            {v.count && <span className="tnum text-muted">{status.data?.buckets?.[v.count] ?? 0}</span>}
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
        <div className="grid grid-cols-2 items-center gap-2 border-b border-line bg-surface-2 p-3 sm:flex sm:flex-wrap">
          <div className="relative col-span-2 min-w-[220px] flex-1 sm:max-w-sm">
            <Search className="absolute top-3 left-3 size-4 text-faint" aria-hidden />
            <input
              aria-label="Search by company or domain"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder="Search by company or website"
              className="h-10 w-full rounded-[var(--radius-control)] border border-line-strong bg-surface pr-3 pl-9 text-body text-ink outline-none focus:border-primary focus:shadow-[0_0_0_3px_var(--primary-soft)]"
            />
          </div>
          <Select aria-label="Status" value={search.status ?? ""} onChange={(e) => set({ status: e.target.value || undefined, hold: e.target.value === "held" ? search.hold : undefined })} className="w-full sm:w-auto">
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
          <div className="col-span-2 flex items-center gap-1 sm:col-span-1 sm:ml-auto">
            <Select aria-label="Sort by" value={search.sort ?? "newest"} onChange={(e) => set({ sort: e.target.value === "newest" ? undefined : e.target.value, dir: undefined })} className="min-w-0 flex-1 sm:w-auto sm:flex-none">
              {SORTS.map(([key, label]) => (
                <option key={key} value={key}>
                  Sort: {label}
                </option>
              ))}
            </Select>
            <Button variant="secondary" aria-label={`Sort direction: ${dirNow === "asc" ? "ascending" : "descending"}`} title="Reverse the order" onClick={() => set({ dir: dirNow === "asc" ? "desc" : "asc" })} className="h-10 px-3">
              {dirNow === "asc" ? <ArrowUp className="size-4" aria-hidden /> : <ArrowDown className="size-4" aria-hidden />}
            </Button>
          </div>
          {filtered && (
            <Button variant="ghost" size="sm" onClick={() => void navigate({ search: {}, replace: true })}>
              <X className="size-3.5" aria-hidden /> Clear
            </Button>
          )}
          {moreOpen && <div className="col-span-2 grid grid-cols-2 items-center gap-2 border-t border-line pt-3 sm:flex sm:basis-full sm:flex-wrap">
          <Select aria-label="Hold reason" value={search.hold ?? ""} onChange={(e) => set({ hold: e.target.value || undefined, status: e.target.value ? "held" : search.status })} className="w-full sm:w-auto">
            <option value="">Any hold</option>
            {HOLD_REASONS.map((h) => (
              <option key={h} value={h}>
                {describeHold(h).label}
              </option>
            ))}
          </Select>
          <Select aria-label="Source" value={search.source ?? ""} onChange={(e) => set({ source: e.target.value || undefined })} className="w-full sm:w-auto">
            <option value="">Any source</option>
            {SOURCES.map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </Select>
          <Select aria-label="Minimum fit" value={search.fit ?? ""} onChange={(e) => set({ fit: e.target.value ? Number(e.target.value) : undefined })} className="w-full sm:w-auto">
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
          <div className="relative overflow-x-auto">
            <table className="w-full text-left">
              <thead className="text-label font-semibold tracking-wide text-faint uppercase">
                <tr className="border-b border-line">
                  <SortHead by="name" className="px-4 py-3">
                    Company
                  </SortHead>
                  <SortHead by="status" className="hidden px-3 py-3 sm:table-cell">
                    Status
                  </SortHead>
                  <th className="hidden px-3 py-3 lg:table-cell">Stage</th>
                  <SortHead by="fit" className="px-3 py-3 text-center">
                    Fit
                  </SortHead>
                  <th className="hidden px-3 py-3 md:table-cell">Contact</th>
                  <th className="hidden px-3 py-3 xl:table-cell">Email</th>
                  <th className="hidden px-3 py-3 text-right xl:table-cell">AI credits</th>
                  <SortHead by="updated" className="hidden px-3 py-3 xl:table-cell">
                    Changed
                  </SortHead>
                  <th className="hidden px-4 py-3 sm:table-cell">
                    <span className="sr-only">Links</span>
                  </th>
                </tr>
              </thead>
              <tbody className={cx("divide-y divide-line", leads.isFetching && leads.isPlaceholderData && "opacity-60")}>
                {items.map((company, row) => {
                  const hold = company.hold_reason ? describeHold(company.hold_reason) : null;
                  const info = companyStatus(company);
                  const s = company.summary;
                  return (
                    <tr key={company.id} className="group transition-colors hover:bg-surface-2">
                      <td className="px-4 py-3.5">
                        <div className="flex items-center gap-3">
                          <LeadIcon domain={company.domain} name={company.name ?? company.domain} />
                          <div className="min-w-0">
                            <Link to="/leads/$companyId" params={{ companyId: company.id }} className="font-semibold text-ink hover:text-primary">
                              {company.name ?? company.domain}
                            </Link>
                            <div className="flex items-center gap-1.5 text-small text-muted">
                              {company.name && <Mono>{company.domain}</Mono>}
                              {company.country_code && <span>{company.name ? "· " : ""}{company.country_code}</span>}
                              {company.priority !== 5 && <span title="Priority (1 is first)">· P{company.priority}</span>}
                            </div>
                            <div className="mt-1 sm:hidden">
                              <Chip tone={info.family}>{info.label}</Chip>
                              {hold && <span className="ml-2 text-small text-attention">{hold.label}</span>}
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="hidden px-3 py-3.5 sm:table-cell">
                        <Chip tone={info.family}>{info.label}</Chip>
                        {hold && <div className="mt-1 text-small text-attention">{hold.label}</div>}
                        {company.status === "failed" && company.last_error && (
                          <div className={cx("mt-1 max-w-[16rem] truncate text-small", info.family === "error" ? "text-error" : "text-muted")} title={plainError(company.last_error)}>
                            {plainError(company.last_error)}
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
                      <td className="tnum hidden px-3 py-3.5 text-right text-small text-ink-2 xl:table-cell">{s ? credits(s.credits_milli) : "—"}</td>
                      <td className="hidden px-3 py-3.5 text-small whitespace-nowrap text-muted xl:table-cell">
                        <span title={`Added ${when(company.created_at)}`}>{ago(company.updated_at ?? company.created_at)}</span>
                      </td>
                      <td className="hidden px-4 py-3.5 text-right sm:table-cell">
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
