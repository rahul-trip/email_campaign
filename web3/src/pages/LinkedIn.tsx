/**
 * Hot leads: every LinkedIn message written for a confirmed decision-maker, best fit first. Filter
 * by state, hot, whether an email could be proven, fit, country and text; sort any way; each row
 * folds (the first is open) and has a one-click "copy the note and open their profile".
 * Nothing is sent from here: the messages are pasted into LinkedIn by hand.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ChevronDown, ExternalLink, Flame, X } from "lucide-react";
import { useEffect, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { isViewing, useCurrent } from "../app/session";
import { CopyNoteButton, LinkedInDraftCard } from "../components/LinkedInDraft";
import { cx } from "../lib/cx";
import { ago } from "../lib/format";
import type { LinkedInSearch } from "../router";
import { Button, buttonClass, Card, Chip, Empty, PageHeader, Problem, Segmented, Select, Skeleton } from "../ui/core";
import { FilterBar, FilterChip, SearchBox, SortControl, useDebounced } from "../ui/filters";
import { LeadIcon } from "../ui/lead";
import { FitRing } from "../ui/viz";

type Row = Schemas["LinkedInDraftRowOut"];
const PAGE = 50;
const SORTS = [
  ["fit", "Best fit"],
  ["newest", "Newest"],
  ["company", "Company A to Z"],
] as const;
const NATURAL = { fit: "desc", newest: "desc", company: "asc" } as const;

/** A lead nobody could find a provable address for: LinkedIn is the way in. */
export const hasNoEmail = (row: Pick<Row, "company_status" | "failure_kind">) => row.company_status === "failed" && (row.failure_kind === "no_person" || row.failure_kind === "no_email");

export function LinkedInPage() {
  const { workspace } = useCurrent();
  const queryClient = useQueryClient();
  const search = useSearch({ from: "/linkedin" });
  const navigate = useNavigate({ from: "/linkedin" });
  const set = (change: Partial<LinkedInSearch>) => void navigate({ search: (prev) => ({ ...prev, ...change }), replace: true });
  const state = search.state ?? "drafted";
  const [limit, setLimit] = useState(PAGE);
  const [typed, setTyped] = useState(search.q ?? "");
  const settled = useDebounced(typed);
  useEffect(() => setTyped(search.q ?? ""), [search.q]);
  useEffect(() => {
    if ((settled.trim() || undefined) !== search.q) set({ q: settled.trim() || undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settled]);

  const sort = search.sort ?? (state === "drafted" ? "fit" : "newest");
  const direction = search.dir ?? NATURAL[sort];
  const query = { state, q: search.q, hot: search.hot ? true : undefined, no_email: search.email === "none" ? true : search.email === "has" ? false : undefined, min_fit: search.fit, country: search.country, sort, direction, limit } as const;
  const list = useQuery({ queryKey: ["linkedin", "page", query], queryFn: () => ok(client.GET("/api/linkedin", { params: { query } })), placeholderData: (previous) => previous });
  // Header counts for the messages still to send, whatever the filters say.
  const count = (extra: { hot?: boolean; no_email?: boolean }) => useQuery({ queryKey: ["linkedin", "count", extra], queryFn: () => ok(client.GET("/api/linkedin", { params: { query: { state: "drafted", limit: 1, ...extra } } })) }).data?.total;
  const toSend = count({});
  const hot = count({ hot: true });
  const noEmail = count({ no_email: true });

  const rows = list.data?.items ?? [];
  const total = list.data?.total ?? 0;
  const [open, setOpen] = useState<Record<string, boolean>>({});
  const isOpen = (id: string, index: number) => (id in open ? open[id]! : index === 0);
  const all = (value: boolean) => setOpen(Object.fromEntries(rows.map((r) => [r.item.id, value])));
  const filtered = Boolean(search.q || search.hot || search.email || search.fit || search.country);
  const refresh = () => {
    for (const key of ["linkedin", "companies", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };

  return (
    <>
      <PageHeader
        title="Hot leads"
        subtitle="Hot leads first. A connection note and a first message for each confirmed decision-maker, written before their email is found, so a lead with no email we could prove still has a way in. Copy them into LinkedIn yourself: nothing is sent from here."
        actions={
          <div className="flex flex-wrap gap-2">
            <Chip tone="primary">{toSend ?? "–"} to send</Chip>
            <Chip tone="attention">
              <Flame className="size-3.5" aria-hidden /> {hot ?? "–"} hot
            </Chip>
            <Chip>{noEmail ?? "–"} with no email we could prove</Chip>
          </div>
        }
      />

      <div className="mb-3" data-tour="linkedin-filter">
        <Segmented
          label="Show"
          value={state}
          onChange={(v) => set({ state: v === "drafted" ? undefined : v, sort: undefined, dir: undefined })}
          options={[
            ["drafted", "To send"],
            ["sent", "Sent"],
            ["skipped", "Skipped"],
          ]}
        />
      </div>

      <Card className="mb-4 overflow-hidden p-0">
        <div className="border-b border-line">
          <FilterBar
            active={[search.hot, search.email, search.fit, search.country].filter(Boolean).length}
            search={<SearchBox label="Search by company, website or person" placeholder="Search company, website or person" value={typed} onChange={setTyped} />}
            controls={
              <>
                <FilterChip active={!!search.hot} onClick={() => set({ hot: search.hot ? undefined : true })}>
                  <Flame className="size-3.5" aria-hidden /> Hot only
                </FilterChip>
                <FilterChip active={search.email === "none"} onClick={() => set({ email: search.email === "none" ? undefined : "none" })}>
                  No email
                </FilterChip>
                <FilterChip active={search.email === "has"} onClick={() => set({ email: search.email === "has" ? undefined : "has" })}>
                  Has email
                </FilterChip>
                <Select aria-label="Minimum fit" value={search.fit ?? ""} onChange={(e) => set({ fit: e.target.value ? Number(e.target.value) : undefined })}>
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
              </>
            }
            trailing={
              <>
                <SortControl value={sort} options={SORTS} direction={direction} onSort={(v) => set({ sort: v, dir: undefined })} onDirection={() => set({ dir: direction === "asc" ? "desc" : "asc" })} />
                {filtered && (
                  <Button variant="ghost" size="sm" onClick={() => void navigate({ search: { state: search.state }, replace: true })}>
                    <X className="size-3.5" aria-hidden /> Clear
                  </Button>
                )}
              </>
            }
          />
        </div>
        <div className="flex items-center justify-between px-4 py-2 text-small text-muted">
          <span>{list.isSuccess ? `${total} message${total === 1 ? "" : "s"}${filtered ? " match" : ""}` : "Loading…"}</span>
          <span className="flex gap-3">
            <button type="button" className="font-semibold text-primary hover:underline" onClick={() => all(true)}>
              Expand all
            </button>
            <button type="button" className="font-semibold text-primary hover:underline" onClick={() => all(false)}>
              Collapse all
            </button>
          </span>
        </div>
      </Card>

      <Problem error={list.error} className="mb-3" />
      {list.isPending ? (
        <Skeleton rows={4} />
      ) : rows.length === 0 ? (
        <Card>
          <Empty
            title={filtered ? "No message matches" : state === "drafted" ? "Nothing to send yet" : "Nothing here"}
            action={filtered ? <Button variant="secondary" size="sm" onClick={() => void navigate({ search: { state: search.state }, replace: true })}>Clear filters</Button> : <Link to="/leads" className={buttonClass("secondary", "sm")}>Browse leads</Link>}
          >
            {filtered ? "Try fewer filters." : state === "drafted" ? "Messages are written when a lead's people are found and a person with a LinkedIn profile is a confirmed decision-maker." : "Messages you mark here will be listed."}
          </Empty>
        </Card>
      ) : (
        // On a phone the leads are cards to swipe through, one after another; from a tablet up they are a list.
        <div
          role="region"
          aria-label="Hot leads, swipe sideways on a phone"
          tabIndex={0}
          className="-mx-4 flex snap-x snap-mandatory items-start gap-3 overflow-x-auto scroll-px-4 px-4 pb-3 outline-none focus-visible:ring-2 focus-visible:ring-primary sm:mx-0 sm:block sm:space-y-3 sm:overflow-visible sm:px-0 sm:pb-0 [&>*]:w-[88%] [&>*]:shrink-0 [&>*]:snap-start sm:[&>*]:w-auto"
          data-tour="linkedin-list"
        >
          {rows.map((row, index) => (
            <LeadRow key={row.item.id} row={row} open={isOpen(row.item.id, index)} onToggle={() => setOpen((o) => ({ ...o, [row.item.id]: !isOpen(row.item.id, index) }))} readOnly={isViewing(workspace)} onChanged={refresh} />
          ))}
          {total > rows.length && (
            <div className="flex items-center justify-center self-stretch pt-1 sm:self-auto">
              <Button variant="secondary" onClick={() => setLimit(limit + PAGE)}>
                Show more ({total - rows.length} left)
              </Button>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function LeadRow({ row, open, onToggle, readOnly, onChanged }: { row: Row; open: boolean; onToggle: () => void; readOnly: boolean; onChanged: () => void }) {
  const name = row.company_name ?? row.domain;
  const noEmail = hasNoEmail(row);
  const id = `lead-row-${row.item.id}`;
  const quick = row.item.state === "drafted" && !readOnly;
  return (
    <Card className="min-w-0 overflow-hidden p-0">
      {/* On a phone the pieces stack: who and what on top, the one-tap button underneath. */}
      <div className="flex flex-col sm:flex-row sm:items-center">
        <button type="button" aria-expanded={open} aria-controls={id} onClick={onToggle} className="flex min-w-0 flex-1 items-start gap-3 p-3 text-left sm:p-4">
          <ChevronDown className={cx("mt-2.5 size-4 shrink-0 text-muted transition-transform", !open && "-rotate-90")} aria-hidden />
          <LeadIcon domain={row.domain} name={name} />
          <span className="min-w-0 flex-1">
            <span className="block break-words font-semibold text-ink">{name}</span>
            <span className="block break-words text-small text-muted">{[row.person, row.title].filter(Boolean).join(" · ") || "Decision-maker"}</span>
            <span className="mt-1.5 flex flex-wrap items-center gap-1.5">
              {row.hot && (
                <Chip tone="attention" title="A fit score above 80">
                  <Flame className="size-3.5" aria-hidden /> Hot
                </Chip>
              )}
              {noEmail && <Chip title="No email address could be proven, so LinkedIn is the way in">No email we could prove</Chip>}
              {row.country_code && <Chip>{row.country_code}</Chip>}
              {row.item.state === "sent" && <Chip tone="good">Sent {ago(row.item.sent_at)}</Chip>}
            </span>
            {!open && <span className="mt-1.5 line-clamp-2 block break-words text-small text-ink-2">“{row.item.note}”</span>}
          </span>
          <span className="shrink-0">
            <FitRing score={row.fit_score} size={40} />
          </span>
        </button>
        {quick && (
          <div className="px-3 pb-3 sm:shrink-0 sm:p-4 sm:pl-0">
            <CopyNoteButton note={row.item.note} profile={row.profile} className="w-full justify-center sm:w-auto" />
          </div>
        )}
      </div>
      {open && (
        <div id={id} className="min-w-0 space-y-3 border-t border-line p-3 sm:p-4">
          {row.fit_reason && (
            <p className="text-small text-muted">
              <span className="font-semibold text-ink-2">Why it fits: </span>
              {row.fit_reason}
            </p>
          )}
          <LinkedInDraftCard draft={row.item} person={row.person} profile={row.profile} readOnly={readOnly} onChanged={onChanged} />
          <Link to="/leads/$companyId" params={{ companyId: row.item.company_id }} className="inline-flex items-center gap-1 text-small font-semibold text-primary hover:underline">
            Open lead <ExternalLink className="size-3" aria-hidden />
          </Link>
        </div>
      )}
    </Card>
  );
}
