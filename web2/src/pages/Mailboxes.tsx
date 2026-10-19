import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, Mail, Plus, RefreshCw, XCircle } from "lucide-react";
import { useState } from "react";
import { client, ok } from "../api/client";
import { Button, Callout, Card, Empty, Field, Input, PageHeader, Problem, QueryState, SaveNote } from "../components/ui";
import { cx } from "../lib/cx";

export function MailboxesPage() {
  const queryClient = useQueryClient();
  const boxes = useQuery({ queryKey: ["mailboxes"], queryFn: () => ok(client.GET("/api/settings/mailboxes")) });
  const [adding, setAdding] = useState(false);
  const [address, setAddress] = useState("");
  const [ref, setRef] = useState("env:EMAIL_PASSWORD");
  const add = useMutation({
    mutationFn: () => ok(client.POST("/api/settings/mailboxes", { body: { address: address.trim(), credentials_ref: ref.trim() } })),
    onSuccess: () => {
      setAddress("");
      setAdding(false);
      void queryClient.invalidateQueries({ queryKey: ["mailboxes"] });
    },
  });
  const check = useMutation({
    mutationFn: (id: string) => ok(client.POST("/api/settings/mailboxes/{mailbox_id}/dns-check", { params: { path: { mailbox_id: id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["mailboxes"] }),
  });

  return (
    <>
      <PageHeader
        title="Mailboxes"
        subtitle="The mailboxes you send from, and whether their domain's email authentication is set up."
        actions={
          !adding && (
            <Button onClick={() => setAdding(true)}>
              <Plus className="size-4" aria-hidden /> Record a mailbox
            </Button>
          )
        }
      />
      <Callout tone="info" className="mb-5 text-[13px]">
        Drafts are saved, and the Sent folder is read, with the login in the server&apos;s <code className="font-mono">.env</code> file (<code className="font-mono">EMAIL_ADDRESS</code>, <code className="font-mono">EMAIL_PASSWORD</code>). Record the same mailbox here to check its DNS; keep the two the same.
      </Callout>

      {adding && (
        <Card title="Record a mailbox" className="mb-5">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Address">
              <Input type="email" placeholder="you@yourcompany.com" value={address} onChange={(e) => setAddress(e.target.value)} autoFocus />
            </Field>
            <Field label="Where the password lives" hint="A name such as env:EMAIL_PASSWORD, never the password itself.">
              <Input value={ref} onChange={(e) => setRef(e.target.value)} className="font-mono" />
            </Field>
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <Button busy={add.isPending} disabled={!address.includes("@") || !ref.trim()} onClick={() => add.mutate()}>
              Record mailbox
            </Button>
            <Button variant="secondary" onClick={() => setAdding(false)}>
              Cancel
            </Button>
            <SaveNote mutation={add} done="Mailbox recorded." />
          </div>
        </Card>
      )}

      <Problem error={check.error} className="mb-4" />
      <QueryState query={boxes}>
        {(all) =>
          all.length === 0 ? (
            <Card>
              <Empty icon={<Mail className="size-8" />} title="No mailbox recorded" action={!adding && <Button onClick={() => setAdding(true)}>Record a mailbox</Button>}>
                Record the mailbox from your .env file to check that SPF, DKIM and DMARC are set up for its domain.
              </Empty>
            </Card>
          ) : (
            <div className="space-y-4">
              {all.map((box) => {
                const report = box.dns_check as Record<string, { ok: boolean; detail: string }> | null;
                const checking = check.isPending && check.variables === box.id;
                return (
                  <Card
                    key={box.id}
                    title={<span className="font-mono">{box.address}</span>}
                    subtitle={`${box.sending_domain} · ${box.gateway.toUpperCase()} · ${box.status} · up to ${box.daily_cap} a day once sending is automatic`}
                    actions={
                      <Button variant="secondary" size="sm" busy={checking} onClick={() => check.mutate(box.id)}>
                        <RefreshCw className="size-3.5" aria-hidden /> {report ? "Check DNS again" : "Check DNS"}
                      </Button>
                    }
                  >
                    {report ? (
                      <div className="grid gap-3 md:grid-cols-3">
                        {(["spf", "dkim", "dmarc"] as const).map((key) => {
                          const record = report[key];
                          return (
                            <div key={key} className={cx("rounded-lg border p-3 text-xs", record?.ok ? "border-line bg-surface-low" : "border-error/30 bg-error-container/50")}>
                              <div className="flex items-center justify-between">
                                <span className="font-mono font-semibold uppercase">{key}</span>
                                <span className={cx("inline-flex items-center gap-1 font-semibold", record?.ok ? "text-good" : "text-error")}>
                                  {record?.ok ? <CheckCircle2 className="size-3.5" aria-hidden /> : <XCircle className="size-3.5" aria-hidden />}
                                  {record?.ok ? "Set up" : "Problem"}
                                </span>
                              </div>
                              <p className="mt-1.5 break-words font-mono text-[11px] text-muted">{record?.detail || "No details reported."}</p>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="flex items-center gap-2 text-xs text-muted">
                        <Clock className="size-3.5" aria-hidden /> DNS has not been checked yet.
                      </p>
                    )}
                  </Card>
                );
              })}
            </div>
          )
        }
      </QueryState>
    </>
  );
}
