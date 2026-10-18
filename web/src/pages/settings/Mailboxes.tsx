import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../../api/client";
import { Badge, Button, Card, Field, Input, Problem, QueryState, SaveNote } from "../../components/ui";

export function Mailboxes() {
  const queryClient = useQueryClient();
  const boxes = useQuery({ queryKey: ["mailboxes"], queryFn: () => ok(client.GET("/api/settings/mailboxes")) });
  const [address, setAddress] = useState("");
  const [ref, setRef] = useState("env:EMAIL_PASSWORD");
  const add = useMutation({
    mutationFn: () => ok(client.POST("/api/settings/mailboxes", { body: { address: address.trim(), credentials_ref: ref.trim() } })),
    onSuccess: () => {
      setAddress("");
      void queryClient.invalidateQueries({ queryKey: ["mailboxes"] });
    },
  });
  const check = useMutation({
    mutationFn: (id: string) => ok(client.POST("/api/settings/mailboxes/{mailbox_id}/dns-check", { params: { path: { mailbox_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mailboxes"] }),
  });
  return (
    <Card title="Mailboxes">
      <p className="mb-4 text-sm text-muted">
        This list records the mailboxes you send from and checks their email authentication (SPF, DKIM, DMARC). Saving drafts and the Sent sync log in with the settings in your <code>.env</code> file (<code>IMAP_HOST</code>, <code>EMAIL_ADDRESS</code>, <code>EMAIL_PASSWORD</code>), so keep the two the same.
      </p>
      <div className="grid items-start gap-3 sm:grid-cols-[2fr_2fr_auto]">
        <Field label="Address">
          <Input type="email" placeholder="you@yourcompany.com" value={address} onChange={(e) => setAddress(e.target.value)} />
        </Field>
        <Field label="Where the password lives" hint="A name such as env:EMAIL_PASSWORD, never the password itself.">
          <Input value={ref} onChange={(e) => setRef(e.target.value)} />
        </Field>
        <div className="flex items-center gap-3 sm:pt-6">
          <Button disabled={!address.includes("@") || add.isPending} onClick={() => add.mutate()}>
            Add mailbox
          </Button>
          <SaveNote mutation={add} done="Mailbox added." />
        </div>
      </div>
      <div className="mt-4">
        <Problem error={check.error} />
      </div>
      <QueryState query={boxes}>
        {(all) => (
          <div className="mt-2 space-y-3">
            {all.length === 0 && <p className="py-4 text-sm text-muted">No mailbox recorded yet.</p>}
            {all.map((box) => {
              const report = box.dns_check as Record<string, { ok: boolean; detail: string }> | null;
              const checking = check.isPending && check.variables === box.id;
              return (
                <div key={box.id} className="rounded-md border border-line p-3 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="flex flex-wrap items-center gap-2">
                      <strong className="break-all">{box.address}</strong>
                      <Badge>{box.gateway}</Badge>
                      <span className="text-muted">cap {box.daily_cap}/day</span>
                    </span>
                    <Button variant="secondary" disabled={checking} onClick={() => check.mutate(box.id)}>
                      {checking ? "Checking…" : "Check DNS"}
                    </Button>
                  </div>
                  {report ? (
                    <ul className="mt-3 space-y-1.5">
                      {(["spf", "dkim", "dmarc"] as const).map((k) => (
                        <li key={k} className="flex items-start gap-2">
                          <span className="w-16 shrink-0">
                            <Badge tone={report[k]?.ok ? "green" : "red"}>{k.toUpperCase()}</Badge>
                          </span>
                          <span>{report[k]?.detail}</span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mt-2 text-xs text-muted">DNS has not been checked yet.</p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </QueryState>
    </Card>
  );
}
