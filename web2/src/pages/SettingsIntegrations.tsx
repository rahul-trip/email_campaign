/** Settings → Integrations: the address and secret other systems use to push targets in. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { useState } from "react";
import { client, ok } from "../api/client";
import { isViewing, useCurrent } from "../app/session";
import { Button, Callout, Card, Confirm, Problem, QueryState } from "../components/ui";

export function Integrations() {
  const { workspace } = useCurrent();
  const admin = workspace.role === "admin" && !isViewing(workspace);
  const info = useQuery({ queryKey: ["webhook"], queryFn: () => ok(client.GET("/api/integrations/webhook")), enabled: admin });
  const [asking, setAsking] = useState(false);
  const [shown, setShown] = useState<string | null>(null);
  const rotate = useMutation({
    mutationFn: () => ok(client.POST("/api/integrations/webhook/rotate")),
    onSuccess: (made) => {
      setShown(made.secret);
      setAsking(false);
      void info.refetch();
    },
  });
  if (!admin) return <Callout>Only workspace admins manage integrations.</Callout>;
  const url = `${window.location.origin}${info.data?.path ?? ""}`;
  return (
    <div className="space-y-5">
    <Card tour="integrations-webhook" title="Intake webhook" subtitle="Let a CRM, a form or a script add targets here. Requests are signed, so nothing else can.">
      <QueryState query={info}>
        {(data) => {
          const url = `${window.location.origin}${data.path}`;
          return (
            <div className="space-y-4 text-[13px]">
              <div>
                <div className="mb-1 text-xs font-medium">Send a POST to</div>
                <div className="flex items-center gap-2">
                  <code className="min-w-0 flex-1 break-all rounded-lg border border-line bg-surface-low px-2.5 py-1.5 font-mono text-xs">{url}</code>
                  <Button variant="secondary" size="sm" onClick={() => void navigator.clipboard?.writeText(url)} aria-label="Copy the address">
                    <Copy className="size-3.5" aria-hidden />
                  </Button>
                </div>
              </div>
              {shown && (
                <Callout tone="attention" title="Your signing secret. Copy it now: it is not shown again.">
                  <code className="mt-1 block break-all font-mono text-xs">{shown}</code>
                </Callout>
              )}
              <Signing />
              <div className="flex items-center gap-3">
                <Button variant={data.configured ? "secondary" : "primary"} busy={rotate.isPending} onClick={() => (data.configured ? setAsking(true) : rotate.mutate())}>
                  {data.configured ? "Make a new secret" : "Turn the webhook on"}
                </Button>
                <span className="text-xs text-muted">{data.configured ? "A secret is set." : "Off until you make a secret."}</span>
              </div>
              <Problem error={rotate.error} />
            </div>
          );
        }}
      </QueryState>
      {asking && (
        <Confirm title="Make a new secret?" confirmLabel="Make a new secret" busy={rotate.isPending} error={rotate.error} onClose={() => setAsking(false)} onConfirm={() => rotate.mutate()}>
          The old secret stops working at once. Update every system that sends here with the new one.
        </Confirm>
      )}
    </Card>
    <BodyFormat />
    <BodyExample url={url} />
    </div>
  );
}

/** Text in a box with a one-click copy, for things people paste into other systems. */
function CodeBlock({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative">
      <pre aria-label={label} className="overflow-x-auto rounded-lg border border-line bg-surface-low p-3 pr-12 font-mono text-xs leading-relaxed">
        {text}
      </pre>
      <Button
        variant="secondary"
        size="sm"
        className="absolute right-2 top-2"
        aria-label={`Copy ${label}`}
        onClick={() => {
          void navigator.clipboard?.writeText(text);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        }}
      >
        {copied ? <Check className="size-3.5" aria-hidden /> : <Copy className="size-3.5" aria-hidden />}
      </Button>
    </div>
  );
}

function Signing() {
  return (
    <p className="text-xs text-muted">
      Send the body as JSON with two headers: <code className="font-mono">X-Timestamp</code> (the time in seconds) and <code className="font-mono">X-Signature</code>, which is <code className="font-mono">sha256=</code> followed by the HMAC-SHA256 of <code className="font-mono">timestamp.body</code> made with your secret. A request more than five minutes old is refused. The body is described and shown below.
    </p>
  );
}

const SINGLE = `{
  "event_id": "<a unique id for this event>",
  "website": "<company website or domain>",
  "company": "<company name>",
  "country": "<country, for example UK or GB>",
  "person": "<full name of someone to write to>",
  "title": "<their job title>",
  "email": "<their work email>",
  "linkedin": "<their LinkedIn profile address>",
  "notes": "<anything worth knowing>",
  "priority": 0
}`;

const MANY = `{
  "event_id": "<a unique id for this event>",
  "targets": [
    { "website": "<...>", "company": "<...>", "country": "<...>" },
    { "website": "<...>", "person": "<...>", "email": "<...>" }
  ]
}`;

const FIELDS: [string, string, string][] = [
  ["event_id", "Always", "Any text, unique per event. Sending the same one again changes nothing, so a retry is safe."],
  ["website", "One of website, company or email", "The company's website or domain, for example acme.com."],
  ["company", "One of website, company or email", "The company's name. Without a website, it is looked up for you."],
  ["email", "Optional", "A person's work email. Its domain can stand in for the website."],
  ["person", "Optional", "A full name. This person is tried first when the email is written."],
  ["title", "Optional", "Their job title."],
  ["linkedin", "Optional", "Their LinkedIn profile address."],
  ["country", "Optional", "Name or code, for example UK, GB or Germany. Decides the country rule."],
  ["notes", "Optional", "Context the writer may use."],
  ["priority", "Optional", "A number; higher goes first."],
  ["targets", "Instead of the fields above", "A list of up to 200 targets, each with the same fields. One event_id covers the whole list."],
];

function BodyFormat() {
  return (
    <Card tour="integrations-format" title="Request body" subtitle="The JSON your system sends. Copy either shape as a starting point.">
      <div className="space-y-4 text-[13px]">
        <div>
          <div className="mb-1 text-xs font-medium">One target</div>
          <CodeBlock label="one-target body" text={SINGLE} />
        </div>
        <div>
          <div className="mb-1 text-xs font-medium">Several targets in one request</div>
          <CodeBlock label="several-targets body" text={MANY} />
        </div>
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-xs">
            <thead className="bg-surface-low text-left text-muted">
              <tr>
                <th className="px-3 py-1.5 font-medium">Field</th>
                <th className="px-3 py-1.5 font-medium">When</th>
                <th className="px-3 py-1.5 font-medium">What it is</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {FIELDS.map(([field, when, what]) => (
                <tr key={field} className="align-top">
                  <td className="px-3 py-1.5 font-mono">{field}</td>
                  <td className="px-3 py-1.5 text-muted">{when}</td>
                  <td className="px-3 py-1.5">{what}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted">The answer lists each target as accepted, merged into a lead you already have, or refused, with the reason.</p>
      </div>
    </Card>
  );
}

function BodyExample({ url }: { url: string }) {
  const body = `{
  "event_id": "crm-2026-10-27-0001",
  "targets": [
    {
      "website": "northwind-energy.co.uk",
      "company": "Northwind Energy",
      "country": "UK",
      "person": "Priya Shah",
      "title": "Head of Trading",
      "notes": "Met at the grid forecasting meetup"
    },
    {
      "website": "sunvale.de",
      "company": "Sunvale GmbH",
      "country": "Germany"
    }
  ]
}`;
  const curl = `BODY='${body.replace(/\s*\n\s*/g, " ")}'
TS=$(date +%s)
SIG=$(printf '%s.%s' "$TS" "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | sed 's/^.* //')

curl -X POST '${url}' \\
  -H 'Content-Type: application/json' \\
  -H "X-Timestamp: $TS" \\
  -H "X-Signature: sha256=$SIG" \\
  --data "$BODY"`;
  const answer = `{
  "duplicate": false,
  "batch_id": "01a17...",
  "rows": [
    { "status": "accepted", "domain": "northwind-energy.co.uk", "reason": null },
    { "status": "accepted", "domain": "sunvale.de", "reason": null }
  ]
}`;
  return (
    <Card tour="integrations-example" title="Example" subtitle="A complete request you can run from a terminal, after setting WEBHOOK_SECRET to your secret.">
      <div className="space-y-4 text-[13px]">
        <div>
          <div className="mb-1 text-xs font-medium">Body</div>
          <CodeBlock label="example body" text={body} />
        </div>
        <div>
          <div className="mb-1 text-xs font-medium">Sending it with curl (signed)</div>
          <CodeBlock label="example curl command" text={curl} />
        </div>
        <div>
          <div className="mb-1 text-xs font-medium">What comes back</div>
          <CodeBlock label="example answer" text={answer} />
        </div>
      </div>
    </Card>
  );
}
