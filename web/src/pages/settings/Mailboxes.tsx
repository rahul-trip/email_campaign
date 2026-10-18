import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../../api/client";
import { Badge, Button, Card, Field, Input, Problem } from "../../components/ui";
import { useSave } from "./shared";

export function Mailboxes() {
  const queryClient = useQueryClient();
  const boxes = useQuery({ queryKey: ["mailboxes"], queryFn: () => ok(client.GET("/api/settings/mailboxes")) });
  const [address, setAddress] = useState("");
  const [ref, setRef] = useState("env:EMAIL_PASSWORD");
  const add = useSave("mailboxes", () => ok(client.POST("/api/settings/mailboxes", { body: { address, credentials_ref: ref } })));
  const check = useMutation({
    mutationFn: (id: string) => ok(client.POST("/api/settings/mailboxes/{mailbox_id}/dns-check", { params: { path: { mailbox_id: id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mailboxes"] }),
  });
  return (
    <Card title="Mailboxes">
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Address">
          <Input value={address} onChange={(e) => setAddress(e.target.value)} />
        </Field>
        <Field label="Where the password lives" hint="A name, never the password itself.">
          <Input value={ref} onChange={(e) => setRef(e.target.value)} />
        </Field>
        <Button disabled={!address.includes("@")} onClick={() => add.mutate(undefined)}>
          Add mailbox
        </Button>
      </div>
      <Problem error={add.error ?? check.error} />
      {boxes.data?.map((box) => {
        const report = box.dns_check as Record<string, { ok: boolean; detail: string }> | null;
        return (
          <div key={box.id} className="mt-4 rounded-md border border-line p-3 text-sm">
            <div className="flex items-center justify-between">
              <span>
                <strong>{box.address}</strong> <Badge>{box.gateway}</Badge> <span className="text-muted">cap {box.daily_cap}/day</span>
              </span>
              <Button variant="secondary" onClick={() => check.mutate(box.id)}>
                Check DNS
              </Button>
            </div>
            {report && (
              <ul className="mt-2 space-y-0.5">
                {(["spf", "dkim", "dmarc"] as const).map((k) => (
                  <li key={k}>
                    <Badge tone={report[k]?.ok ? "green" : "red"}>{k.toUpperCase()}</Badge> {report[k]?.detail}
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </Card>
  );
}
