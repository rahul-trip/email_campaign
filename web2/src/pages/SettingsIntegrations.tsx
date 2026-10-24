/** Settings → Integrations: the address and secret other systems use to push targets in. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Copy } from "lucide-react";
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
  return (
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
              <p className="text-xs text-muted">
                Body: JSON with an <code className="font-mono">event_id</code> (sending the same one twice changes nothing) and either one target (<code className="font-mono">website</code> or <code className="font-mono">company</code>, optional <code className="font-mono">country</code>) or a <code className="font-mono">targets</code> list of up to 200. Headers: <code className="font-mono">X-Timestamp</code> (seconds) and <code className="font-mono">X-Signature</code> = <code className="font-mono">sha256=</code> + HMAC-SHA256 of <code className="font-mono">timestamp.body</code> with the secret. Requests older than five minutes are refused.
              </p>
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
  );
}
