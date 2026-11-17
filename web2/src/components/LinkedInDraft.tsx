import { useMutation } from "@tanstack/react-query";
import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { cx } from "../lib/cx";
import { ago, when } from "../lib/format";
import { Button, Callout, Confirm, Field, Problem, Textarea } from "./ui";

type Draft = Schemas["LinkedInDraftOut"];
const NOTE_LIMIT = 200; // a free LinkedIn account's connection note

/** A text with a Copy button. LinkedIn is pasted into by hand: nothing here is ever sent. */
function Copyable({ label, text, hint }: { label: string; text: string; hint?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-ink">{label}</span>
        <span className="flex items-center gap-2">
          {hint && <span className="text-caption text-muted">{hint}</span>}
          <Button
            variant="secondary"
            size="sm"
            aria-label={`Copy the ${label.toLowerCase()}`}
            onClick={() => {
              void navigator.clipboard?.writeText(text);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            }}
          >
            {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />} {copied ? "Copied" : "Copy"}
          </Button>
        </span>
      </div>
      <p className="whitespace-pre-wrap rounded-lg border border-line bg-surface-low p-3 text-body leading-relaxed">{text}</p>
    </div>
  );
}

/**
 * One person's LinkedIn note and message, to copy and paste into LinkedIn. On the lead page and
 * on the LinkedIn page. ``profile`` opens their LinkedIn page.
 */
export function LinkedInDraftCard({
  draft,
  person,
  profile,
  readOnly,
  onChanged,
}: {
  draft: Draft;
  person?: string | null;
  profile?: string | null;
  readOnly?: boolean;
  onChanged: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(draft.note);
  const [message, setMessage] = useState(draft.message);
  const [confirming, setConfirming] = useState(false);
  const done = () => {
    setEditing(false);
    onChanged();
  };
  const path = { params: { path: { linkedin_id: draft.id } } };
  const save = useMutation({ mutationFn: () => ok(client.PATCH("/api/linkedin/{linkedin_id}", { ...path, body: { note, message } })), onSuccess: done });
  const skip = useMutation({ mutationFn: () => ok(client.POST("/api/linkedin/{linkedin_id}/skip", path)), onSuccess: done });
  const restore = useMutation({ mutationFn: () => ok(client.POST("/api/linkedin/{linkedin_id}/restore", path)), onSuccess: done });
  const rewrite = useMutation({
    mutationFn: () => ok(client.POST("/api/contacts/{contact_id}/linkedin", { params: { path: { contact_id: draft.contact_id } } })),
    onSuccess: (fresh) => {
      setNote(fresh.note);
      setMessage(fresh.message);
      done();
    },
  });
  const sent = useMutation({
    mutationFn: () => ok(client.POST("/api/linkedin/{linkedin_id}/sent", path)),
    onSuccess: () => {
      setConfirming(false);
      onChanged();
    },
  });
  const isSent = draft.state === "sent";
  const skipped = draft.state === "skipped";
  return (
    <div className={cx("space-y-3 rounded-lg border border-line p-3", skipped && "opacity-70")}>
      <div className="flex flex-wrap items-center gap-2">
        {person && <span className="font-semibold">{person}</span>}
        {profile && (
          <a href={profile} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-caption font-medium text-primary hover:underline">
            Open their LinkedIn <ExternalLink className="size-3" aria-hidden />
          </a>
        )}
        {isSent && draft.sent_at && (
          <span className="rounded-full bg-good-container px-2 py-0.5 text-caption font-medium text-on-good-container" title={when(draft.sent_at)}>
            Sent on LinkedIn {ago(draft.sent_at)}
          </span>
        )}
        {skipped && <span className="rounded-full bg-surface-container px-2 py-0.5 text-caption font-medium text-muted">Skipped</span>}
        {draft.edited && !isSent && <span className="text-caption text-muted">edited by you</span>}
      </div>

      {draft.issues.length > 0 && !isSent && (
        <Callout tone="attention" title="Check this before you send it">
          <ul className="list-disc pl-5">
            {draft.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </Callout>
      )}

      {editing ? (
        <div className="space-y-3">
          <Field label={`Connection note (${note.trim().length} of ${NOTE_LIMIT} characters)`}>
            <Textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <Field label="Message after they accept">
            <Textarea rows={8} value={message} onChange={(e) => setMessage(e.target.value)} />
          </Field>
          <div className="flex gap-2">
            <Button size="sm" busy={save.isPending} disabled={!note.trim() || !message.trim()} onClick={() => save.mutate()}>
              Save
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <>
          <Copyable label="Connection note" text={draft.note} hint={`${draft.note.length} of ${NOTE_LIMIT} characters`} />
          <Copyable label="Message after they accept" text={draft.message} />
        </>
      )}

      {!readOnly && !isSent && !editing && (
        <div className="flex flex-wrap gap-1">
          <Button size="sm" onClick={() => setConfirming(true)} disabled={skipped}>
            Mark sent on LinkedIn
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
            Edit
          </Button>
          <Button variant="ghost" size="sm" busy={rewrite.isPending} onClick={() => rewrite.mutate()} title="Write a fresh note and message">
            Rewrite
          </Button>
          {skipped ? (
            <Button variant="ghost" size="sm" busy={restore.isPending} onClick={() => restore.mutate()}>
              Use it again
            </Button>
          ) : (
            <Button variant="ghost" size="sm" busy={skip.isPending} onClick={() => skip.mutate()}>
              Skip
            </Button>
          )}
        </div>
      )}
      <Problem error={save.error ?? skip.error ?? restore.error ?? rewrite.error} />
      {confirming && (
        <Confirm
          title="Mark this as sent on LinkedIn?"
          confirmLabel="Yes, I sent it"
          busy={sent.isPending}
          error={sent.error}
          onConfirm={() => sent.mutate()}
          onClose={() => setConfirming(false)}
        >
          Say so only after you pasted it into LinkedIn and sent it. The email to this lead then waits, so the person is not contacted twice at once; an email waiting for review is withdrawn. Release the hold on the lead when you want the email written again.
        </Confirm>
      )}
    </div>
  );
}
