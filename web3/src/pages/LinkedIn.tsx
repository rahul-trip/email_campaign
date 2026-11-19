/**
 * LinkedIn ready, laid out like Emails ready: the companies waiting on the left (on a phone, a row to
 * swipe), and on the right the one you picked, with every person written to there, one under another.
 * All the people at a company are together, so a company is worked through in one visit.
 * Filter by state, hot, whether an email could be proven, fit, country and text; sort any way.
 * J and K move between companies. Nothing is sent from here: the messages are pasted into LinkedIn
 * by hand.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { CheckCircle2, ChevronLeft, ChevronRight, ExternalLink, Flame, Keyboard, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { isViewing, useCurrent } from "../app/session";
import { LinkedInDraftCard } from "../components/LinkedInDraft";
import { cx } from "../lib/cx";
import type { LinkedInSearch } from "../router";
import { Button, buttonClass, Card, Chip, Empty, Kbd, Label, PageHeader, Problem, Segmented, Select, Skeleton } from "../ui/core";
import { FilterBar, FilterChip, SearchBox, SortControl, useDebounced } from "../ui/filters";
import { LeadIcon } from "../ui/lead";
import { Dialog } from "../ui/overlay";
import { FitRing } from "../ui/viz";

type Row = Schemas["LinkedInDraftRowOut"];
const PAGE = 200; // messages, the most the server gives at once; companies are kept whole within them
const SORTS = [
  ["fit", "Best fit"],
  ["newest", "Newest"],
  ["company", "Company A to Z"],
] as const;
const NATURAL = { fit: "desc", newest: "desc", company: "asc" } as const;

/** A lead nobody could find a provable address for: LinkedIn is the way in. */
export const hasNoEmail = (row: Pick<Row, "company_status" | "failure_kind">) => row.company_status === "failed" && (row.failure_kind === "no_person" || row.failure_kind === "no_email");

/** A company and everyone written to there. The company's own facts (fit, hot, why) are the first row's. */
export type Group = { id: string; rows: Row[] };

/** The messages grouped by company, in the order each company first appears, so the chosen sort holds. */
export function groupByCompany(rows: readonly Row[]): Group[] {
  const groups = new Map<string, Group>();
  for (const row of rows) {
    const id = row.item.company_id;
    const group = groups.get(id);
    if (group) group.rows.push(row);
    else groups.set(id, { id, rows: [row] });
  }
  return [...groups.values()];
}

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
  const groups = groupByCompany(rows);
  const [selected, setSelected] = useState<string | null>(null);
  const [showKeys, setShowKeys] = useState(false);
  // When the chosen company leaves the list (all its messages are sent), the next one takes its place.
  const index = Math.max(0, groups.findIndex((g) => g.id === selected));
  const current = groups[index] as Group | undefined;
  const filtered = Boolean(search.q || search.hot || search.email || search.fit || search.country);
  const readOnly = isViewing(workspace);
  const refresh = () => {
    for (const key of ["linkedin", "companies", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };

  const go = useCallback(
    (step: number) => {
      if (groups.length === 0) return;
      setSelected(groups[(index + step + groups.length) % groups.length]!.id);
    },
    [groups, index],
  );
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement;
      if (target.closest("input, textarea, select, [contenteditable]") || event.metaKey || event.ctrlKey || event.altKey) return;
      if (event.key === "j") go(1);
      if (event.key === "k") go(-1);
      if (event.key === "?") setShowKeys(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  return (
    <>
      <PageHeader
        title="LinkedIn ready"
        subtitle="Hot leads first. A connection note and a first message for each confirmed decision-maker, written before their email is found, so a lead with no email we could prove still has a way in. Everyone at a company is together. Copy the messages into LinkedIn yourself: nothing is sent from here."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone="primary">{toSend ?? "–"} to send</Chip>
            <Chip tone="attention">
              <Flame className="size-3.5" aria-hidden /> {hot ?? "–"} hot
            </Chip>
            <Chip>{noEmail ?? "–"} with no email we could prove</Chip>
            {groups.length > 0 && (
              <>
                <span className="tnum text-small text-muted">
                  {index + 1} of {groups.length}
                </span>
                <Button variant="secondary" size="sm" aria-label="Previous company (K)" onClick={() => go(-1)}>
                  <ChevronLeft className="size-4" />
                </Button>
                <Button variant="secondary" size="sm" aria-label="Next company (J)" onClick={() => go(1)}>
                  <ChevronRight className="size-4" />
                </Button>
                <Button variant="ghost" size="sm" onClick={() => setShowKeys(true)}>
                  <Keyboard className="size-4" aria-hidden /> Shortcuts
                </Button>
              </>
            )}
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
          <span>{list.isSuccess ? `${total} message${total === 1 ? "" : "s"} for ${groups.length} ${groups.length === 1 ? "company" : "companies"}${filtered ? " match" : ""}${total > rows.length ? ` · showing ${rows.length}` : ""}` : "Loading…"}</span>
        </div>
      </Card>

      <Problem error={list.error} className="mb-3" />
      {list.isPending ? (
        <Skeleton rows={4} />
      ) : groups.length === 0 ? (
        <Card>
          <Empty
            art={!filtered && state === "drafted" ? <CheckCircle2 className="size-12 text-good-dot" /> : undefined}
            title={filtered ? "No message matches" : state === "drafted" ? "Nothing to send yet" : "Nothing here"}
            action={filtered ? <Button variant="secondary" size="sm" onClick={() => void navigate({ search: { state: search.state }, replace: true })}>Clear filters</Button> : <Link to="/leads" className={buttonClass("secondary", "sm")}>Browse leads</Link>}
          >
            {filtered ? "Try fewer filters." : state === "drafted" ? "Messages are written when a lead's people are found and a person with a LinkedIn profile is a confirmed decision-maker." : "Messages you mark here will be listed."}
          </Empty>
        </Card>
      ) : (
        <>
          {current && <QueueStrip groups={groups} current={current.id} onPick={setSelected} />}
          {current && (
            <div className="mt-4 grid grid-cols-1 gap-5 lg:mt-0 lg:grid-cols-[296px_minmax(0,1fr)]">
              <Queue groups={groups} current={current.id} onPick={setSelected} />
              <Reader key={current.id} group={current} readOnly={readOnly} onChanged={refresh} />
            </div>
          )}
          {total > rows.length && (
            <div className="mt-4 flex justify-center">
              <Button variant="secondary" onClick={() => setLimit(limit + PAGE)}>
                Show more ({total - rows.length} messages left)
              </Button>
            </div>
          )}
        </>
      )}

      {showKeys && (
        <Dialog title="Keyboard shortcuts" onClose={() => setShowKeys(false)}>
          <dl className="grid grid-cols-[7rem_1fr] gap-y-3 text-body">
            {[
              ["J", "Next company"],
              ["K", "Previous company"],
              ["?", "This list"],
            ].map(([key, text]) => (
              <div key={key} className="contents">
                <dt>
                  <Kbd>{key}</Kbd>
                </dt>
                <dd className="text-ink-2">{text}</dd>
              </div>
            ))}
          </dl>
        </Dialog>
      )}
    </>
  );
}

const sentCount = (group: Group) => group.rows.filter((r) => r.item.state === "sent").length;

/** One company as a card the person can pick, with the people written to there under its name. */
function QueueCard({ group, active, onPick, className }: { group: Group; active: boolean; onPick: (id: string) => void; className?: string }) {
  const head = group.rows[0]!;
  const name = head.company_name ?? head.domain;
  const shown = group.rows.slice(0, 3);
  const sent = sentCount(group);
  return (
    <button
      type="button"
      onClick={() => onPick(group.id)}
      aria-current={active ? "true" : undefined}
      className={cx("press w-full rounded-2xl border p-3.5 text-left transition", active ? "border-primary bg-primary-soft" : "border-line bg-surface hover:border-line-strong hover:bg-surface-2", className)}
    >
      <div className="flex items-start gap-3">
        <LeadIcon domain={head.domain} name={name} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 truncate text-body font-semibold text-ink">
            {head.hot && <Flame className="size-3.5 shrink-0 text-attention-dot" aria-label="Hot lead" />}
            <span className="truncate">{name}</span>
          </div>
          <ul className="mt-0.5 space-y-0.5">
            {shown.map((row) => (
              <li key={row.item.id} className="truncate text-small text-ink-2">
                {row.person ?? "Decision-maker"}
                {row.title && <span className="text-muted"> · {row.title}</span>}
              </li>
            ))}
            {group.rows.length > shown.length && <li className="text-small text-muted">and {group.rows.length - shown.length} more</li>}
          </ul>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-label text-muted">
            <span>
              {group.rows.length} {group.rows.length === 1 ? "person" : "people"}
            </span>
            {hasNoEmail(head) && <span title="No email address could be proven, so LinkedIn is the way in">no email</span>}
            {head.country_code && <span>{head.country_code}</span>}
            {sent > 0 && <span className="font-semibold text-good">{sent} sent</span>}
          </div>
        </div>
        <FitRing score={head.fit_score} size={34} />
      </div>
    </button>
  );
}

function Queue({ groups, current, onPick }: { groups: Group[]; current: string; onPick: (id: string) => void }) {
  return (
    <nav aria-label="Companies waiting" data-tour="linkedin-queue" className="hidden flex-col gap-2 lg:flex">
      <Label className="px-1">Companies ({groups.length})</Label>
      <ul className="flex max-h-[calc(100vh-190px)] flex-col gap-2 overflow-y-auto pr-1 pb-2">
        {groups.map((group) => (
          <li key={group.id}>
            <QueueCard group={group} active={group.id === current} onPick={onPick} />
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** On a phone and a tablet the companies are a row to swipe through, with the chosen one kept in view. */
function QueueStrip({ groups, current, onPick }: { groups: Group[]; current: string; onPick: (id: string) => void }) {
  const ref = useRef<HTMLUListElement>(null);
  useEffect(() => {
    const card = ref.current?.querySelector<HTMLElement>('[aria-current="true"]')?.parentElement;
    const strip = ref.current;
    if (!card || !strip) return;
    // Scroll the strip itself, not the page: the person is reading the messages below.
    strip.scrollTo({ left: card.offsetLeft - strip.offsetLeft - 16, behavior: "smooth" });
  }, [current]);
  return (
    <nav aria-label="Companies waiting" data-tour="linkedin-strip" className="min-w-0 lg:hidden">
      <Label className="px-1">Companies ({groups.length}) · swipe to pick</Label>
      <ul ref={ref} className="-mx-4 mt-2 flex snap-x snap-mandatory gap-2 overflow-x-auto scroll-px-4 px-4 pb-2 sm:-mx-6 sm:px-6 sm:scroll-px-6 [&>li]:w-64 [&>li]:shrink-0 [&>li]:snap-start">
        {groups.map((group) => (
          <li key={group.id}>
            <QueueCard group={group} active={group.id === current} onPick={onPick} className="h-full" />
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** The company, why it fits, and a message card for each person written to there. */
function Reader({ group, readOnly, onChanged }: { group: Group; readOnly: boolean; onChanged: () => void }) {
  const head = group.rows[0]!;
  const name = head.company_name ?? head.domain;
  return (
    <div className="flex min-w-0 flex-col gap-4" data-tour="linkedin-reader">
      <Card className="overflow-hidden p-0">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line bg-surface-2 px-4 py-4 sm:px-6">
          <div className="flex min-w-0 items-start gap-3">
            <LeadIcon domain={head.domain} name={name} />
            <div className="min-w-0">
              <div className="break-words text-heading font-semibold text-ink">{name}</div>
              <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                {head.hot && (
                  <Chip tone="attention" title="A fit score above 80">
                    <Flame className="size-3.5" aria-hidden /> Hot
                  </Chip>
                )}
                {hasNoEmail(head) && <Chip title="No email address could be proven, so LinkedIn is the way in">No email we could prove</Chip>}
                {head.country_code && <Chip>{head.country_code}</Chip>}
                <Chip>
                  {group.rows.length} {group.rows.length === 1 ? "person" : "people"}
                </Chip>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <FitRing score={head.fit_score} size={44} />
            <Link to="/leads/$companyId" params={{ companyId: head.item.company_id }} className="inline-flex items-center gap-1 text-small font-semibold text-primary hover:underline">
              Open lead <ExternalLink className="size-3.5" aria-hidden />
            </Link>
          </div>
        </div>
        {head.fit_reason && (
          <p className="px-4 py-3 text-small text-muted sm:px-6">
            <span className="font-semibold text-ink-2">Why it fits: </span>
            {head.fit_reason}
          </p>
        )}
      </Card>

      <section aria-label={`Messages for ${name}`} className="flex min-w-0 flex-col gap-3">
        <Label className="px-1">
          People at {name} ({group.rows.length})
        </Label>
        {group.rows.map((row) => (
          <div key={row.item.id} className="min-w-0">
            <LinkedInDraftCard draft={row.item} person={row.person} title={row.title} profile={row.profile} readOnly={readOnly} onChanged={onChanged} />
          </div>
        ))}
      </section>
    </div>
  );
}
