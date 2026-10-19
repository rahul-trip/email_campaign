import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { diffWords } from "diff";
import { AlertTriangle, Check, CheckCircle2, ChevronLeft, ChevronRight, ExternalLink, Flag, Keyboard, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Button, Callout, Card, Dialog, Empty, Field, Input, Label, PageHeader, Problem, Skeleton } from "../components/ui";
import { cx } from "../lib/cx";
import { words } from "../lib/format";
import { describe, emailStatus, isSafeToSend } from "../lib/status";

type Item = Schemas["ReviewItemOut"];
type Lint = { word_count?: number; reading_grade?: number; issues?: { rule: string; message: string }[] };

/**
 * The checks the server runs on every first email (outbound/domain/copy_lint.py), in the order an
 * operator reads them. Each passes unless the server's lint report names its rule.
 */
const CHECKS: [string, string][] = [
  ["length", "Length 50–85 words, footer excluded"],
  ["subject", "Subject 2–5 words, lower case"],
  ["reading_level", "Reading grade 6.5 or lower"],
  ["call_to_action", "Exactly one question"],
  ["links", "No links in the first email"],
  ["address_in_body", "No email address in the body"],
  ["banned_phrase", "No banned phrases"],
  ["footer", "Country footer present"],
];

export function ReviewPage() {
  const queue = useQuery({ queryKey: ["review"], queryFn: () => ok(client.GET("/api/review")), refetchInterval: 10000 });
  const [selected, setSelected] = useState<string | null>(null);
  const [showKeys, setShowKeys] = useState(false);
  const items = queue.data ?? [];
  const index = Math.max(0, items.findIndex((item) => item.message.id === selected));
  const current = items[index] as Item | undefined;

  const go = useCallback(
    (step: number) => {
      if (items.length === 0) return;
      setSelected(items[(index + step + items.length) % items.length].message.id);
    },
    [items, index],
  );

  // J and K move through the queue, unless the operator is typing.
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
              <span className="font-mono text-xs text-muted">
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

      {queue.isPending && <Skeleton rows={6} />}
      {queue.isError && <Problem error={queue.error} />}
      {queue.isSuccess && items.length === 0 && (
        <Card>
          <Empty icon={<CheckCircle2 className="size-8 text-good" />} title="The queue is clear" action={<Link to="/runs" className="text-xs font-semibold text-primary hover:underline">Start a run</Link>}>
            New emails appear here when a run writes them. Add targets and start a run to fill the queue.
          </Empty>
        </Card>
      )}

      {current && (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[300px_minmax(0,1fr)_340px] lg:grid-cols-[280px_minmax(0,1fr)]">
          <Queue items={items} current={current.message.id} onPick={setSelected} />
          <Reader
            key={current.message.id}
            item={current}
            onDone={() => {
              // Move on to the next email; the finished one leaves the list when it reloads.
              const next = items[index + 1] ?? items[index - 1];
              setSelected(next ? next.message.id : null);
            }}
          />
        </div>
      )}

      {showKeys && (
        <Dialog title="Keyboard shortcuts" onClose={() => setShowKeys(false)}>
          <dl className="grid grid-cols-[5rem_1fr] gap-y-2">
            {[
              ["J", "Next email"],
              ["K", "Previous email"],
              ["Ctrl Enter", "Approve (in the editor too)"],
              ["?", "This list"],
            ].map(([key, text]) => (
              <div key={key} className="contents">
                <dt>
                  <kbd className="rounded border border-line bg-surface-low px-1.5 font-mono text-xs">{key}</kbd>
                </dt>
                <dd>{text}</dd>
              </div>
            ))}
          </dl>
        </Dialog>
      )}
    </>
  );
}

function Queue({ items, current, onPick }: { items: Item[]; current: string; onPick: (id: string) => void }) {
  return (
    <nav aria-label="Emails waiting" data-tour="review-queue" className="hidden flex-col gap-2 lg:flex">
      <Label className="px-1">Waiting ({items.length})</Label>
      <ul className="flex max-h-[calc(100vh-200px)] flex-col gap-2 overflow-y-auto pr-1">
        {items.map((item) => {
          const active = item.message.id === current;
          return (
            <li key={item.message.id}>
              <button
                type="button"
                onClick={() => onPick(item.message.id)}
                aria-current={active ? "true" : undefined}
                className={cx(
                  "w-full rounded-xl border p-3 text-left transition-colors",
                  active ? "border-primary-container bg-primary-fixed/40 ring-1 ring-primary-container/30" : "border-line bg-surface hover:border-outline",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-[13px] font-semibold">{item.company.name ?? item.company.domain}</span>
                  {item.company.country_code && <span className="font-mono text-[10px] text-muted">{item.company.country_code}</span>}
                </div>
                <div className="mt-0.5 truncate text-xs">{item.contact.full_name ?? "Name unknown"}</div>
                <div className="truncate text-[11px] text-muted">{item.contact.title ?? "Title unknown"}</div>
                <div className="mt-2 flex items-center justify-between gap-2 border-t border-line pt-1.5">
                  <span className="truncate font-mono text-[10px] text-muted">{item.message.subject}</span>
                  {item.flagged && (
                    <span className="inline-flex shrink-0 items-center gap-1 rounded bg-attention-container px-1.5 text-[10px] font-semibold text-on-attention-container">
                      <Flag className="size-3" aria-hidden /> Flagged
                    </span>
                  )}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function Reader({ item, onDone }: { item: Item; onDone: () => void }) {
  const queryClient = useQueryClient();
  const messageId = item.message.id;
  const detail = useQuery({
    queryKey: ["review", messageId],
    queryFn: () => ok(client.GET("/api/review/{message_id}", { params: { path: { message_id: messageId } } })),
  });
  const [text, setText] = useState(item.message.generated_body);
  const [rejecting, setRejecting] = useState(false);
  const edited = text !== item.message.generated_body;

  const finished = () => {
    for (const key of ["review", "status", "companies", "lead"]) void queryClient.invalidateQueries({ queryKey: [key] });
    onDone();
  };
  const approve = useMutation({
    mutationFn: () =>
      ok(
        client.POST("/api/review/{message_id}/approve", {
          params: { path: { message_id: messageId } },
          body: { edited_body: edited ? text : null, row_version: item.message.row_version },
        }),
      ),
    onSuccess: finished,
  });

  const lint = (item.message.lint_report ?? {}) as Lint;
  const failing = new Set((lint.issues ?? []).map((issue) => issue.rule));
  const address = item.contact.emails.find((e) => e.is_primary) ?? item.contact.emails[0];
  const company = item.company;
  const research = (company.research ?? {}) as Record<string, unknown>;
  const hooks = (research.hooks as string[] | undefined) ?? [];
  const answers = Object.entries(company.research_answers ?? {});
  const decision = (company.policy_decision ?? {}) as { outcome?: string; rule?: string; policy_version?: number; reasons?: string[] };

  return (
    <>
      <div className="flex min-w-0 flex-col gap-4">
        <Card tour="review-editor">
          <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-[15px] font-semibold">
                  To {item.contact.full_name ?? "unknown"} <span className="font-mono text-[13px] font-normal text-muted">&lt;{address?.email ?? "no address"}&gt;</span>
                </h2>
                {address && <StatusBadge status={describe(emailStatus, address.status)} title={isSafeToSend(address.status) ? "Safe to send" : "Not safe to send"} />}
              </div>
              <p className="mt-1 text-xs text-muted">
                Subject: <strong className="font-semibold text-ink">{item.message.subject}</strong>
                {address && (
                  <>
                    {" · "}
                    {words(address.provenance)}
                    {address.found_by && `, found by ${address.found_by}`}
                    {address.verified_by && `, checked by ${address.verified_by}`}
                  </>
                )}
              </p>
            </div>
            <Link to="/leads/$companyId" params={{ companyId: company.id }} className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
              Open lead <ExternalLink className="size-3" aria-hidden />
            </Link>
          </div>

          <label className="mt-3 block">
            <span className="mb-1.5 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-muted">
              Email, exactly as it will be drafted
              {edited && <span className="rounded bg-attention-container px-1.5 py-0.5 font-mono normal-case tracking-normal text-on-attention-container">edited by you</span>}
            </span>
            <textarea
              aria-label="Email text"
              rows={16}
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey) && !approve.isPending) approve.mutate();
              }}
              className="w-full resize-y rounded-lg border border-outline bg-surface p-3.5 text-[15px] leading-6 outline-none focus:border-primary-container focus:ring-2 focus:ring-primary-container/20"
            />
          </label>
          <p className="mt-1.5 text-[11px] text-muted">The legal footer for the country is part of the text. An edit that removes it is refused.</p>

          {edited && (
            <div className="mt-3">
              <Label className="mb-1">Your changes</Label>
              <pre aria-label="Changes" className="whitespace-pre-wrap rounded-lg border border-line bg-surface-low p-3 font-sans text-[13px] leading-relaxed">
                {diffWords(item.message.generated_body, text).map((part, i) => (
                  <span key={i} className={part.added ? "rounded bg-good-container text-on-good-container" : part.removed ? "rounded bg-error-container text-on-error-container line-through" : undefined}>
                    {part.value}
                  </span>
                ))}
              </pre>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <Button busy={approve.isPending} onClick={() => approve.mutate()}>
                <Check className="size-4" aria-hidden /> {edited ? "Approve with my edit" : "Approve"}
              </Button>
              <Button variant="secondary" disabled={!edited} onClick={() => setText(item.message.generated_body)}>
                <RotateCcw className="size-3.5" aria-hidden /> Undo my edits
              </Button>
            </div>
            <Button variant="danger-ghost" onClick={() => setRejecting(true)}>
              <X className="size-4" aria-hidden /> Reject…
            </Button>
          </div>
          <p className="mt-2 text-[11px] text-muted">Approving does not send anything: the next run saves it as a draft in your mailbox.</p>
          <Problem error={approve.error} className="mt-3" />
        </Card>

        <div className="xl:hidden">
          <Context company={company} hooks={hooks} answers={answers} notes={detail.data?.notes ?? []} lint={lint} failing={failing} flagged={item.flagged} decision={decision} />
        </div>
      </div>

      <div className="hidden xl:block">
        <Context company={company} hooks={hooks} answers={answers} notes={detail.data?.notes ?? []} lint={lint} failing={failing} flagged={item.flagged} decision={decision} />
      </div>

      {rejecting && <RejectDialog messageId={messageId} company={company.name ?? company.domain} onClose={() => setRejecting(false)} onDone={finished} />}
    </>
  );
}

function Context({
  company,
  hooks,
  answers,
  notes,
  lint,
  failing,
  flagged,
  decision,
}: {
  company: Schemas["CompanyOut"];
  hooks: string[];
  answers: [string, unknown][];
  notes: string[];
  lint: Lint;
  failing: Set<string>;
  flagged: boolean;
  decision: { outcome?: string; rule?: string; policy_version?: number; reasons?: string[] };
}) {
  const research = (company.research ?? {}) as Record<string, unknown>;
  return (
    <div data-tour="review-checks" className="flex flex-col gap-4">
      <Card title="Why this lead">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold">{company.name ?? company.domain}</span>
          <span className={cx("rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold", (company.fit_score ?? 0) >= 70 ? "bg-good-container text-on-good-container" : "bg-surface-container")}>
            fit {company.fit_score ?? "?"}/100
          </span>
        </div>
        {company.fit_reason && <p className="mt-1 text-xs text-muted">{company.fit_reason}</p>}
        {Boolean(research.summary) && <p className="mt-2 text-[13px] leading-relaxed">{String(research.summary)}</p>}
        {hooks.length > 0 && (
          <>
            <Label className="mb-1 mt-3">What the research found</Label>
            <ul className="list-disc space-y-0.5 pl-4 text-[13px]">
              {hooks.map((hook) => (
                <li key={hook}>{hook}</li>
              ))}
            </ul>
          </>
        )}
        {answers.length > 0 && (
          <>
            <Label className="mb-1 mt-3">Your research questions</Label>
            <dl className="space-y-1.5 text-[13px]">
              {answers.map(([question, answer]) => (
                <div key={question}>
                  <dt className="text-xs text-muted">{question}</dt>
                  <dd>{String(answer)}</dd>
                </div>
              ))}
            </dl>
          </>
        )}
        {notes.map((note) => (
          <Callout key={note} tone="attention" className="mt-3">
            <strong>Your note:</strong> {note}
          </Callout>
        ))}
      </Card>

      <Card title="Checks" actions={flagged ? <span className="rounded bg-attention-container px-1.5 py-0.5 text-[11px] font-semibold text-on-attention-container">Flagged</span> : undefined}>
        <ul className="space-y-1.5 text-[13px]">
          {CHECKS.map(([rule, label]) => {
            const bad = failing.has(rule);
            return (
              <li key={rule} className="flex items-start gap-2">
                {bad ? <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-attention" aria-label="Problem" /> : <Check className="mt-0.5 size-3.5 shrink-0 text-good" aria-label="Passed" />}
                <span className={bad ? "font-medium" : undefined}>{label}</span>
              </li>
            );
          })}
        </ul>
        {(lint.issues ?? []).length > 0 && (
          <Callout tone="attention" className="mt-3">
            <ul className="list-disc space-y-0.5 pl-4">
              {lint.issues?.map((issue) => <li key={issue.rule + issue.message}>{issue.message}</li>)}
            </ul>
          </Callout>
        )}
        {lint.word_count != null && (
          <p className="mt-2 font-mono text-[11px] text-muted">
            As written: {lint.word_count} words, reading grade {lint.reading_grade}. Your edits are checked again when you approve.
          </p>
        )}
        <dl className="mt-3 space-y-1 border-t border-line pt-3 text-xs">
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
      </Card>
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
      tone="danger"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" busy={reject.isPending} disabled={!reason.trim()} onClick={() => reject.mutate()}>
            Reject
          </Button>
        </>
      }
    >
      <p className="text-muted">Rejecting ends work on this company: no email is drafted and it leaves the queue. The reason is kept with the lead.</p>
      <Field label="Reason">
        <Input autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="For example: wrong person, or not a fit" />
      </Field>
      <Problem error={reject.error} />
    </Dialog>
  );
}
