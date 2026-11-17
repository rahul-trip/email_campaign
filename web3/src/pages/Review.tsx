/**
 * Review: the queue on the left, the email as it will be drafted in the middle (the focal point),
 * and why this lead on the right as folding sections. Everything web2's Review did is here:
 * hot leads first, J/K, Ctrl+Enter, edit with a word diff, ask for changes, write again, reject
 * with a reason, acknowledge skipped checks, the 14 copy checks, history, notes, country rule.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearch } from "@tanstack/react-router";
import { diffWords } from "diff";
import { AlertTriangle, Check, CheckCircle2, ChevronLeft, ChevronRight, ExternalLink, Flag, Flame, Keyboard, Newspaper, RotateCcw, Wand2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { isViewing, useCurrent } from "../app/session";
import { cx } from "../lib/cx";
import { ago, when, words } from "../lib/format";
import { Avatar, Button, Callout, Card, Checkbox, Chip, Empty, Field, Input, Kbd, Label, Mono, PageHeader, Problem, Skeleton, Textarea } from "../ui/core";
import { EmailChip, FitBreakdown, qualificationOf } from "../ui/lead";
import { Dialog, useToast } from "../ui/overlay";
import { Section, SectionGroup } from "../ui/sections";
import { FitRing } from "../ui/viz";

type Item = Schemas["ReviewItemOut"];
type Lint = { word_count?: number; reading_grade?: number; issues?: { rule: string; message: string }[] };

const SUGGESTIONS = ["More formal.", "Warmer and more personal.", "Shorter.", "More specific about what we offer.", "Softer ask."];

const checksFor = (low: number, high: number): [string, string][] => [
  ["length", `Length ${low}–${high} words, greeting, sign-off and footer excluded`],
  ["subject", "Subject 2–6 words, lower case"],
  ["reading_level", "Reading grade 12 or lower"],
  ["call_to_action", "One or two questions, with a clear ask at the end"],
  ["bullets", "Paragraphs, no bullet lists"],
  ["dashes", "At most one em dash"],
  ["links", "No links in the first email"],
  ["address_in_body", "No email address in the body"],
  ["banned_phrase", "No stock or machine-sounding phrases"],
  ["source", "The news it opens with is a real source from the research"],
  ["opening", "Opens with the recent news when there is some"],
  ["grounded", "Every fact is in the research notes or your facts"],
  ["human", "Reads like a person wrote it"],
  ["footer", "Country footer present"],
];

export function ReviewPage() {
  const queue = useQuery({ queryKey: ["review"], queryFn: () => ok(client.GET("/api/review")), refetchInterval: 10000 });
  const daily = useQuery({ queryKey: ["daily", 14], queryFn: () => ok(client.GET("/api/reports/daily", { params: { query: { days: 14 } } })) });
  const { message } = useSearch({ from: "/review" });
  const [selected, setSelected] = useState<string | null>(message ?? null);
  const [showKeys, setShowKeys] = useState(false);
  const status = useQuery({ queryKey: ["status"], queryFn: () => ok(client.GET("/api/status")), refetchInterval: 5000 });
  const approved = status.data?.by_status?.approved ?? 0;
  // Hot leads first, so the emails that always need you are not buried; the rest keep their order.
  const items = [...(queue.data ?? [])].sort((a, b) => Number(b.company.hot) - Number(a.company.hot));
  const index = Math.max(0, items.findIndex((item) => item.message.id === selected));
  const current = items[index] as Item | undefined;
  const reviewedToday = daily.data?.days.at(-1)?.reviewed ?? 0;
  const best = Math.max(0, ...(daily.data?.days ?? []).map((d) => d.reviewed));

  const go = useCallback(
    (step: number) => {
      if (items.length === 0) return;
      setSelected(items[(index + step + items.length) % items.length]!.message.id);
    },
    [items, index],
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
        title="Review"
        subtitle={queue.isSuccess ? (items.length ? `${items.length} email${items.length === 1 ? "" : "s"} waiting. Nothing reaches your mailbox until you approve it.` : "Nothing is waiting for you.") : "Loading…"}
        actions={
          items.length > 0 && (
            <>
              <Chip tone="good" title={`Best day in the last two weeks: ${best}`}>
                {reviewedToday} reviewed today{best > reviewedToday ? ` · best ${best}` : ""}
              </Chip>
              <span className="tnum text-small text-muted">
                {index + 1} of {items.length}
              </span>
              <Button variant="secondary" size="sm" aria-label="Previous email (K)" onClick={() => go(-1)}>
                <ChevronLeft className="size-4" />
              </Button>
              <Button variant="secondary" size="sm" aria-label="Next email (J)" onClick={() => go(1)}>
                <ChevronRight className="size-4" />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setShowKeys(true)}>
                <Keyboard className="size-4" aria-hidden /> Shortcuts
              </Button>
            </>
          )
        }
      />

      {queue.isPending && <Skeleton rows={8} />}
      {queue.isError && <Problem error={queue.error} />}
      {queue.isSuccess && items.length === 0 && (
        <Card>
          <Empty art={<CheckCircle2 className="size-12 text-good-dot" />} title="The queue is clear ✨" action={<Link to="/runs" className="text-body font-semibold text-primary hover:underline">See discovery runs →</Link>}>
            New emails appear here as runs write them.
            {approved > 0 && (
              <span className="mt-3 flex flex-wrap items-center justify-center gap-2">
                {approved} approved email{approved === 1 ? " is" : "s are"} saved as drafts within 15 minutes, or now: <StartNow />
              </span>
            )}
          </Empty>
        </Card>
      )}

      {current && (
        <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[296px_minmax(0,1fr)_360px]">
          <Queue items={items} current={current.message.id} onPick={setSelected} />
          <Reader
            key={current.message.id}
            item={current}
            onDone={(company) => {
              const next = items[index + 1] ?? items[index - 1];
              setSelected(next ? next.message.id : null);
              return next ? next.company.name ?? next.company.domain : company;
            }}
          />
        </div>
      )}

      {showKeys && (
        <Dialog title="Keyboard shortcuts" onClose={() => setShowKeys(false)}>
          <dl className="grid grid-cols-[7rem_1fr] gap-y-3 text-body">
            {[
              ["J", "Next email"],
              ["K", "Previous email"],
              ["Ctrl ↵", "Approve (in the editor too)"],
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

function StartNow() {
  const { workspace } = useCurrent();
  const queryClient = useQueryClient();
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => ok(client.GET("/api/runs")) });
  const start = useMutation({
    mutationFn: () => ok(client.POST("/api/runs", { body: { mode: "manual" } })),
    onSuccess: () => ["runs", "status"].forEach((key) => void queryClient.invalidateQueries({ queryKey: [key] })),
  });
  if (isViewing(workspace)) return null;
  if (start.data)
    return (
      <span className="text-small text-good" role="status">
        Started.{" "}
        <Link to="/runs/$runId" params={{ runId: start.data.id }} className="font-semibold underline">
          Follow it
        </Link>
      </span>
    );
  if (runs.data?.some((r) => r.status === "queued" || r.status === "running")) return <span className="text-small text-muted">A run is already working; it picks this up.</span>;
  return (
    <>
      <Button size="sm" variant="secondary" busy={start.isPending} onClick={() => start.mutate()}>
        Start now
      </Button>
      <Problem error={start.error} />
    </>
  );
}

function Queue({ items, current, onPick }: { items: Item[]; current: string; onPick: (id: string) => void }) {
  return (
    <nav aria-label="Emails waiting" data-tour="review-queue" className="hidden flex-col gap-2 lg:flex">
      <Label className="px-1">Waiting ({items.length})</Label>
      <ul className="flex max-h-[calc(100vh-190px)] flex-col gap-2 overflow-y-auto pr-1 pb-2">
        {items.map((item) => {
          const active = item.message.id === current;
          return (
            <li key={item.message.id}>
              <button
                type="button"
                onClick={() => onPick(item.message.id)}
                aria-current={active ? "true" : undefined}
                className={cx("press w-full rounded-2xl border p-3.5 text-left transition", active ? "border-primary bg-primary-soft shadow-2" : "border-line bg-surface hover:border-line-strong hover:shadow-1")}
              >
                <div className="flex items-start gap-3">
                  <FitRing score={item.company.fit_score} size={34} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5 truncate text-body font-semibold text-ink">
                      {item.company.hot && <Flame className="size-3.5 shrink-0 text-attention-dot" aria-label="Hot lead" />}
                      <span className="truncate">{item.company.name ?? item.company.domain}</span>
                    </div>
                    <div className="truncate text-small text-ink-2">
                      {item.contact.full_name ?? "Name unknown"}
                      {item.contact.title && <span className="text-muted"> · {item.contact.title}</span>}
                    </div>
                    <div className="mt-1 flex items-center gap-2 text-label text-muted">
                      {item.message.created_at && <span title={when(item.message.created_at)}>waited {ago(item.message.created_at).replace(" ago", "")}</span>}
                      {item.flagged && (
                        <span className="inline-flex items-center gap-1 font-semibold text-attention">
                          <Flag className="size-3" aria-hidden /> Flagged
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function Reader({ item, onDone }: { item: Item; onDone: (company: string) => string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const messageId = item.message.id;
  const detail = useQuery({ queryKey: ["review", messageId], queryFn: () => ok(client.GET("/api/review/{message_id}", { params: { path: { message_id: messageId } } })) });
  const [text, setText] = useState(item.message.generated_body);
  const [rejecting, setRejecting] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const edited = text !== item.message.generated_body;
  const skips = item.skips ?? [];
  const opening = (item.message.snippets as { opening?: { headline: string; date?: string; url: string } | null } | null)?.opening;
  const blockedBySkips = skips.length > 0 && !acknowledged;
  const company = item.company;
  const name = company.name ?? company.domain;

  const finished = (what: string) => {
    for (const key of ["review", "status", "companies", "lead", "daily"]) void queryClient.invalidateQueries({ queryKey: [key] });
    const next = onDone(name);
    toast({ tone: "good", title: `${what} · ${name}`, body: next !== name ? `Next: ${next}` : "That was the last one." });
  };
  const [instructions, setInstructions] = useState("");
  const [revisedLint, setRevisedLint] = useState<Lint | null>(null);
  const revise = useMutation({
    mutationFn: () => ok(client.POST("/api/review/{message_id}/revise", { params: { path: { message_id: messageId } }, body: { instructions: instructions.trim(), current_body: text } })),
    onSuccess: (revision) => {
      setText(revision.body);
      setRevisedLint(revision.lint_report as Lint);
      setInstructions("");
    },
  });
  const rewrite = useMutation({ mutationFn: () => ok(client.POST("/api/review/{message_id}/rewrite", { params: { path: { message_id: messageId } } })), onSuccess: () => finished("Sent back to be written again") });
  const approve = useMutation({
    mutationFn: () => ok(client.POST("/api/review/{message_id}/approve", { params: { path: { message_id: messageId } }, body: { edited_body: edited ? text : null, row_version: item.message.row_version, acknowledge_skips: acknowledged } })),
    onSuccess: () => finished(edited ? "Approved with your edit" : "Approved"),
  });

  const lint = (item.message.lint_report ?? {}) as Lint;
  const address = item.contact.emails.find((e) => e.is_primary) ?? item.contact.emails[0];

  return (
    <>
      <div className="flex min-w-0 flex-col gap-4">
        <Card className="overflow-hidden" data-tour="review-editor">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line bg-surface-2 px-6 py-4">
            <div className="flex min-w-0 items-start gap-3">
              <Avatar name={name} />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="truncate text-heading font-semibold text-ink">{item.contact.full_name ?? "Name unknown"}</span>
                  <EmailChip address={address} />
                  {address?.verification_skipped && <Chip tone="attention">Not verified: you skipped the check</Chip>}
                </div>
                <div className="truncate text-small text-muted">
                  {item.contact.title ?? "Title unknown"} at {name} · <Mono>{address?.email ?? "no address"}</Mono>
                </div>
                {address && (
                  <div className="mt-0.5 text-label text-faint">
                    {words(address.provenance)}
                    {address.found_by && `, found by ${address.found_by}`}
                    {address.verified_by && `, checked by ${address.verified_by}`}
                    {address.verified_at && ` ${ago(address.verified_at)}`}
                  </div>
                )}
              </div>
            </div>
            <Link to="/leads/$companyId" params={{ companyId: company.id }} className="inline-flex items-center gap-1 text-small font-semibold text-primary hover:underline">
              Open lead <ExternalLink className="size-3.5" aria-hidden />
            </Link>
          </div>

          <div className="px-6 py-5">
            <div data-tour="review-opening" className={cx("mb-4 flex items-start gap-2 rounded-xl px-3.5 py-2.5 text-small", opening ? "bg-primary-soft text-ink-2" : "bg-surface-2 text-muted")}>
              <Newspaper className="mt-0.5 size-4 shrink-0 text-primary" aria-hidden />
              {opening ? (
                <span>
                  <strong className="text-ink">Opens with:</strong>{" "}
                  <a href={opening.url} target="_blank" rel="noreferrer" className="font-medium text-primary hover:underline">
                    {opening.headline}
                  </a>
                  {opening.date && <span className="ml-1 text-muted">({opening.date})</span>} · check it is right before you approve
                </span>
              ) : (
                <span>Opens with a fact from their own site: research found no dated news about them.</span>
              )}
            </div>

            <div className="text-label font-semibold tracking-wide text-faint uppercase">Subject</div>
            <div className="mt-0.5 mb-4 text-title font-semibold text-ink">{item.message.subject}</div>

            <label className="block">
              <span className="mb-1.5 flex items-center justify-between text-label font-semibold tracking-wide text-faint uppercase">
                Email, exactly as it will be drafted
                {edited && <Chip tone="attention">edited by you</Chip>}
              </span>
              <textarea
                aria-label="Email text"
                rows={16}
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !approve.isPending && !blockedBySkips) approve.mutate();
                }}
                className="email-paper w-full resize-y rounded-2xl border border-line bg-surface p-5 text-ink shadow-[inset_0_1px_2px_rgb(0_0_0/0.03)] outline-none focus:border-primary focus:shadow-[0_0_0_3px_var(--primary-soft)]"
              />
            </label>
            <p className="mt-1.5 text-small text-muted">
              {lint.word_count != null ? `${lint.word_count} words as written · reading grade ${lint.reading_grade}. ` : ""}The legal footer for the country is part of the text; an edit that removes it is refused.
            </p>

            {edited && (
              <div className="mt-4 animate-rise">
                <Label className="mb-1.5">Your changes</Label>
                <pre aria-label="Changes" className="email-paper rounded-xl border border-line bg-surface-2 p-4 font-sans whitespace-pre-wrap text-ink-2">
                  {diffWords(item.message.generated_body, text).map((part, i) => (
                    <span key={i} className={part.added ? "rounded bg-good-soft text-good" : part.removed ? "rounded bg-error-soft text-error line-through" : undefined}>
                      {part.value}
                    </span>
                  ))}
                </pre>
              </div>
            )}

            <div data-tour="review-revise" className="mt-5 rounded-2xl border border-line bg-surface-2 p-4">
              <div className="flex items-center gap-2 font-semibold text-ink">
                <Wand2 className="size-4 text-primary" aria-hidden /> Ask for changes
              </div>
              <p className="mt-0.5 mb-3 text-small text-muted">The text above, with your own edits, is rewritten as you say. Nothing is saved until you approve.</p>
              <div className="mb-2 flex flex-wrap gap-1.5">
                {SUGGESTIONS.map((s) => (
                  <button key={s} type="button" onClick={() => setInstructions(instructions.trim() ? `${instructions.trim()} ${s}` : s)} className="press rounded-full border border-line-strong bg-surface px-3 py-1 text-small text-ink-2 hover:border-primary hover:text-primary">
                    {s}
                  </button>
                ))}
              </div>
              <Textarea aria-label="Instructions for the rewrite" rows={2} value={instructions} onChange={(e) => setInstructions(e.target.value)} placeholder="For example: more formal; mention we already work with two Nordic grid operators; ask for a call in December" />
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <Button size="sm" variant="soft" busy={revise.isPending} disabled={!instructions.trim()} onClick={() => revise.mutate()}>
                  <Wand2 className="size-3.5" aria-hidden /> Rewrite with these changes
                </Button>
                {revise.isPending && <span className="text-small text-muted">Rewriting… this can take a few seconds.</span>}
              </div>
              <Problem error={revise.error} className="mt-2" />
              {revisedLint && (revisedLint.issues ?? []).length > 0 && (
                <Callout tone="attention" className="mt-3" title="The rewrite does not pass every check">
                  <ul className="list-disc space-y-0.5 pl-4">
                    {revisedLint.issues?.map((issue) => (
                      <li key={issue.rule + issue.message}>{issue.message}</li>
                    ))}
                  </ul>
                  <p className="mt-1">You can still approve it: your instructions come first.</p>
                </Callout>
              )}
            </div>

            {skips.length > 0 && (
              <Callout tone="attention" className="mt-4" title="This email relies on checks you skipped" icon={<AlertTriangle className="size-5 text-attention-dot" />}>
                <ul className="mt-1 list-disc space-y-0.5 pl-4" data-tour="review-skips">
                  {skips.map((skip) => (
                    <li key={skip.kind}>{skip.text.charAt(0).toUpperCase() + skip.text.slice(1)}.</li>
                  ))}
                </ul>
                <div className="mt-2">
                  <Checkbox checked={acknowledged} onChange={setAcknowledged} label="I know these checks were skipped, and I approve this email anyway" />
                </div>
              </Callout>
            )}
          </div>

          {/* The action bar stays in view at the bottom of the email. */}
          <div className="sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface/95 px-6 py-4 backdrop-blur">
            <div className="flex flex-wrap items-center gap-2">
              <Button size="lg" busy={approve.isPending} disabled={blockedBySkips} onClick={() => approve.mutate()}>
                <Check className="size-4" aria-hidden /> {edited ? "Approve with my edit" : "Approve"}
                <Kbd>Ctrl ↵</Kbd>
              </Button>
              <Button variant="secondary" disabled={!edited} onClick={() => setText(item.message.generated_body)}>
                <RotateCcw className="size-4" aria-hidden /> Undo my edits
              </Button>
            </div>
            <div className="flex items-center gap-1">
              <Button variant="ghost" busy={rewrite.isPending} onClick={() => rewrite.mutate()} title="Cancel this email and have the next run write a new one to the same person">
                <RotateCcw className="size-4" aria-hidden /> Write it again
              </Button>
              <Button variant="danger" onClick={() => setRejecting(true)}>
                <X className="size-4" aria-hidden /> Reject…
              </Button>
            </div>
            <p className="basis-full text-small text-muted">Approving sends nothing: within 15 minutes it is saved as a draft in your mailbox.</p>
            <Problem error={approve.error ?? rewrite.error} className="basis-full" />
          </div>
        </Card>
        <div className="xl:hidden">
          <Context item={item} detail={detail.data} lint={lint} />
        </div>
      </div>
      <div className="hidden xl:block">
        <Context item={item} detail={detail.data} lint={lint} />
      </div>
      {rejecting && <RejectDialog messageId={messageId} company={name} onClose={() => setRejecting(false)} onDone={() => finished("Rejected")} />}
    </>
  );
}

function Context({ item, detail, lint }: { item: Item; detail?: Schemas["ReviewDetailOut"]; lint: Lint }) {
  const company = item.company;
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const checks = checksFor(Number(settings.data?.email_min_words ?? 120), Number(settings.data?.email_max_words ?? 200));
  const failing = new Set((lint.issues ?? []).map((i) => i.rule));
  const research = (company.research ?? {}) as Record<string, unknown>;
  const hooks = (research.hooks as string[] | undefined) ?? [];
  const answers = Object.entries(company.research_answers ?? {});
  const decision = (company.policy_decision ?? {}) as { outcome?: string; rule?: string; policy_version?: number };
  const qualification = qualificationOf(company);
  const met = qualification?.criteria?.filter((c) => c.kind === "must_have" && c.verdict === "met").length ?? 0;
  const musts = qualification?.criteria?.filter((c) => c.kind === "must_have").length ?? 0;
  const notes = detail?.notes ?? [];
  const history = detail?.history ?? [];

  return (
    <div data-tour="review-checks">
      <SectionGroup storageKey="review-context" toolbar={false} className="space-y-3">
        <Section
          id="why"
          title="Why this lead"
          summary={musts ? `${met} of ${musts} must-haves met${company.hot ? " · hot" : ""}` : (company.fit_reason ?? "Not scored yet")}
          chip={<FitRing score={company.fit_score} size={38} />}
        >
          {company.fit_reason && <p className="mb-3 text-small text-muted">{company.fit_reason}</p>}
          {Boolean(research.summary) && <p className="mb-4 text-body text-ink-2">{String(research.summary)}</p>}
          {qualification && <FitBreakdown data={qualification} />}
          {notes.map((note) => (
            <Callout key={note} tone="attention" className="mt-3">
              <strong>Your note:</strong> {note}
            </Callout>
          ))}
        </Section>
        <Section id="found" title="What research found" summary={hooks.length ? `${hooks.length} talking point${hooks.length === 1 ? "" : "s"}${answers.length ? ` · ${answers.length} answers` : ""}` : "Nothing notable"}>
          {hooks.length > 0 && (
            <ul className="list-disc space-y-1 pl-4 text-body text-ink-2">
              {hooks.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          )}
          {answers.length > 0 && (
            <dl className="mt-3 space-y-2 text-body">
              {answers.map(([q, a]) => (
                <div key={q}>
                  <dt className="text-small text-muted">{q}</dt>
                  <dd className="text-ink-2">{String(a)}</dd>
                </div>
              ))}
            </dl>
          )}
          {!hooks.length && !answers.length && <p className="text-small text-muted">Research found nothing worth opening with.</p>}
        </Section>
        <Section
          id="checks"
          title="Checks"
          summary={failing.size ? `${failing.size} to look at` : "All 14 pass"}
          chip={item.flagged ? <Chip tone="attention">Flagged</Chip> : <Chip tone="good">Passed</Chip>}
        >
          <ul className="space-y-1.5 text-body">
            {checks.map(([rule, label]) => {
              const bad = failing.has(rule);
              return (
                <li key={rule} className="flex items-start gap-2">
                  {bad ? <AlertTriangle className="mt-0.5 size-4 shrink-0 text-attention-dot" aria-label="Problem" /> : <Check className="mt-0.5 size-4 shrink-0 text-good-dot" aria-label="Passed" />}
                  <span className={bad ? "font-medium text-ink" : "text-ink-2"}>{label}</span>
                </li>
              );
            })}
          </ul>
          {(lint.issues ?? []).length > 0 && (
            <Callout tone="attention" className="mt-3">
              <ul className="list-disc space-y-0.5 pl-4">
                {lint.issues?.map((i) => (
                  <li key={i.rule + i.message}>{i.message}</li>
                ))}
              </ul>
            </Callout>
          )}
          <dl className="mt-3 space-y-1 border-t border-line pt-3 text-small">
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Country</dt>
              <dd className="font-mono">{company.country_code ?? "unknown"}</dd>
            </div>
            <div className="flex justify-between gap-2">
              <dt className="text-muted">Company type</dt>
              <dd>{words(company.legal_entity_type)}</dd>
            </div>
            {decision.outcome && (
              <div className="flex justify-between gap-2">
                <dt className="text-muted">Country rule</dt>
                <dd className="text-right">
                  {words(decision.rule ?? decision.outcome)}
                  {decision.policy_version != null && <span className="text-muted"> · v{decision.policy_version}</span>}
                </dd>
              </div>
            )}
          </dl>
        </Section>
        {history.length > 0 && (
          <Section id="history" tour="review-history" title="History of this email" summary={`${history.length} step${history.length === 1 ? "" : "s"} · last ${ago(history.at(-1)!.at)}`}>
            <ol className="space-y-2.5 text-body">
              {history.map((h, i) => (
                <li key={i}>
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className="font-medium text-ink">{h.what}</span>
                    <span className="text-small text-muted" title={when(h.at)}>
                      {ago(h.at)} · {h.actor === "system" ? "the engine" : h.actor === "operator" ? "you" : h.actor.replace(":", " ")}
                    </span>
                  </div>
                  {h.detail && <div className="text-small text-muted">{h.detail}</div>}
                </li>
              ))}
            </ol>
          </Section>
        )}
      </SectionGroup>
    </div>
  );
}

function RejectDialog({ messageId, company, onClose, onDone }: { messageId: string; company: string; onClose: () => void; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const reject = useMutation({
    mutationFn: () => ok(client.POST("/api/review/{message_id}/reject", { params: { path: { message_id: messageId } }, body: { reason: reason.trim() } })),
    onSuccess: () => {
      onClose();
      onDone();
    },
  });
  return (
    <Dialog
      title={`Reject ${company}?`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" busy={reject.isPending} disabled={!reason.trim()} onClick={() => reject.mutate()}>
            Reject
          </Button>
        </>
      }
    >
      <p className="mb-4 text-body text-muted">Rejecting ends work on this company: no email is drafted and it leaves the queue. The reason is kept with the lead.</p>
      <Field label="Reason">
        <Input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: wrong person, or not a fit" />
      </Field>
      <Problem error={reject.error} className="mt-3" />
    </Dialog>
  );
}
