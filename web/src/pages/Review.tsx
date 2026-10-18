import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { diffWords } from "diff";
import { useEffect, useState } from "react";
import { client, isConflict, ok, type Schemas } from "../api/client";
import { Badge, Button, Card, Empty, Input, Problem, Textarea, statusTone, words } from "../components/ui";

type Item = Schemas["ReviewItemOut"];

function Diff({ before, after }: { before: string; after: string }) {
  return (
    <pre className="whitespace-pre-wrap rounded-md bg-gray-50 p-3 text-sm" aria-label="Changes">
      {diffWords(before, after).map((part, index) => (
        <span
          key={index}
          className={part.added ? "bg-green-100" : part.removed ? "bg-red-100 line-through" : undefined}
        >
          {part.value}
        </span>
      ))}
    </pre>
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
  const [reason, setReason] = useState("");
  useEffect(() => setText(item.message.generated_body), [item.message.generated_body, messageId]);

  const finished = () => {
    void queryClient.invalidateQueries({ queryKey: ["review"] });
    void queryClient.invalidateQueries({ queryKey: ["status"] });
    onDone();
  };
  const approve = useMutation({
    mutationFn: () =>
      ok(
        client.POST("/api/review/{message_id}/approve", {
          params: { path: { message_id: messageId } },
          body: { edited_body: text === item.message.generated_body ? null : text, row_version: item.message.row_version },
        }),
      ),
    onSuccess: finished,
  });
  const reject = useMutation({
    mutationFn: () =>
      ok(client.POST("/api/review/{message_id}/reject", { params: { path: { message_id: messageId } }, body: { reason } })),
    onSuccess: finished,
  });

  const company = item.company;
  const research = (company.research ?? {}) as Record<string, unknown>;
  const hooks = (research.hooks as string[] | undefined) ?? [];
  const answers = Object.entries(company.research_answers ?? {});
  const issues = ((item.message.lint_report as { issues?: { rule: string; message: string }[] } | null)?.issues ?? []);
  const edited = text !== item.message.generated_body;

  return (
    <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
      <Card title={`To ${item.contact.full_name ?? "unknown"} <${item.contact.emails[0]?.email ?? "?"}>`}>
        <p className="mb-2 text-sm text-muted">
          Subject: <strong className="text-ink">{item.message.subject}</strong> · {item.contact.title ?? "role unknown"}
        </p>
        <Textarea aria-label="Email text" rows={16} value={text} onChange={(e) => setText(e.target.value)} />
        {edited && (
          <div className="mt-3">
            <h3 className="mb-1 text-xs font-semibold uppercase text-muted">Your changes</h3>
            <Diff before={item.message.generated_body} after={text} />
          </div>
        )}
        <div className="mt-3 space-y-3">
          <Problem error={approve.error ?? reject.error} />
          {isConflict(approve.error) && <p className="text-sm text-amber-700">This email changed. Reload the queue.</p>}
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => approve.mutate()} disabled={approve.isPending}>
              {edited ? "Approve with my edit" : "Approve"}
            </Button>
            <Input aria-label="Reason for rejecting" placeholder="Reason, if rejecting" value={reason} onChange={(e) => setReason(e.target.value)} className="max-w-xs" />
            <Button variant="danger" onClick={() => reject.mutate()} disabled={!reason.trim() || reject.isPending}>
              Reject
            </Button>
          </div>
        </div>
      </Card>

      <div className="space-y-4">
        <Card title="Why this lead">
          <p className="text-sm">
            <strong>{company.name ?? company.domain}</strong> · fit {company.fit_score ?? "?"}
          </p>
          <p className="text-sm text-muted">{company.fit_reason}</p>
          <p className="mt-2 text-sm">{String(research.summary ?? "")}</p>
          {hooks.map((hook) => (
            <p key={hook} className="mt-1 text-sm">
              • {hook}
            </p>
          ))}
          {answers.map(([question, answer]) => (
            <p key={question} className="mt-1 text-sm">
              <span className="text-muted">{question}</span> {String(answer)}
            </p>
          ))}
          {detail.data?.notes.map((note) => (
            <p key={note} className="mt-1 rounded bg-amber-50 p-1.5 text-sm">
              Note: {note}
            </p>
          ))}
        </Card>
        <Card title="Checks">
          <div className="flex flex-wrap gap-1.5">
            <Badge tone={item.flagged ? "red" : "green"}>{item.flagged ? "flagged by linter" : "linter passed"}</Badge>
            {company.country_code && <Badge>{company.country_code}</Badge>}
            <Badge tone={statusTone(company.legal_entity_type)}>{words(company.legal_entity_type)}</Badge>
          </div>
          {issues.map((issue) => (
            <p key={issue.rule + issue.message} className="mt-2 text-sm text-red-800">
              ! {issue.message}
            </p>
          ))}
          <h3 className="mt-3 text-xs font-semibold uppercase text-muted">Country policy decision</h3>
          <pre className="mt-1 overflow-x-auto rounded bg-gray-50 p-2 text-xs">{JSON.stringify(company.policy_decision ?? {}, null, 2)}</pre>
        </Card>
      </div>
    </div>
  );
}

export function ReviewPage() {
  const queue = useQuery({ queryKey: ["review"], queryFn: () => ok(client.GET("/api/review")) });
  const [selected, setSelected] = useState<string | null>(null);
  const items = queue.data ?? [];
  const current = items.find((item) => item.message.id === selected) ?? items[0];

  return (
    <div className="grid gap-4 lg:grid-cols-[16rem_1fr]">
      <Card title={`Waiting (${items.length})`} className="h-fit">
        {queue.isPending && <p className="text-sm text-muted">Loading…</p>}
        {queue.isSuccess && items.length === 0 && <Empty>Nothing to review. Add targets and start a run.</Empty>}
        <ul className="space-y-1">
          {items.map((item) => (
            <li key={item.message.id}>
              <button
                onClick={() => setSelected(item.message.id)}
                className={`w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-gray-100 ${current?.message.id === item.message.id ? "bg-gray-100" : ""}`}
              >
                <span className="block font-medium">{item.company.name ?? item.company.domain}</span>
                <span className="text-xs text-muted">{item.contact.full_name}</span> {item.flagged && <Badge tone="red">flagged</Badge>}
              </button>
            </li>
          ))}
        </ul>
      </Card>
      {current ? <Reader key={current.message.id} item={current} onDone={() => setSelected(null)} /> : <div />}
    </div>
  );
}
