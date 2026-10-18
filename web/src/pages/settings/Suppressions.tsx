import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../../api/client";
import { Button, Card, Empty, Field, Input, Problem, Select, Table, Td, when, words } from "../../components/ui";
import { useSave } from "./shared";

/** Erase one person on request: suppress the address for good and remove what identifies them. */
function Forget() {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const forget = useMutation({
    mutationFn: () => ok(client.POST("/api/privacy/forget", { body: { email: email.trim() } })),
    onSuccess: () => {
      for (const key of ["suppressions", "companies", "lead", "review", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  const result = forget.data;
  return (
    <Card title="Forget an address">
      <p className="mb-3 text-sm text-muted">
        For someone who asks to be erased. Their address goes on the do-not-contact list, their unsent emails are cancelled and any draft in the mailbox is deleted, and their name, title and address are removed from this system. Counts and costs are kept. This cannot be undone.
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Email address">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="min-w-72" />
        </Field>
        <Button
          variant="danger"
          disabled={!email.includes("@") || forget.isPending}
          onClick={() => {
            if (window.confirm(`Erase everything about ${email.trim()} and never contact them again?`)) forget.mutate();
          }}
        >
          Forget this address
        </Button>
      </div>
      <Problem error={forget.error} />
      {result && (
        <p role="status" className="mt-3 text-sm">
          {result.found ? "Done." : "That address was not in the system, but it is now on the do-not-contact list."} {result.messages_cancelled} unsent email(s) cancelled, {result.drafts_deleted} draft(s) deleted.
          {result.drafts_left.length > 0 && <span className="text-red-800"> The mailbox could not delete {result.drafts_left.length} draft(s); remove them by hand.</span>}
        </p>
      )}
    </Card>
  );
}

export function Suppressions() {
  const entries = useQuery({ queryKey: ["suppressions"], queryFn: () => ok(client.GET("/api/settings/suppressions")) });
  const [kind, setKind] = useState<"email" | "domain">("email");
  const [value, setValue] = useState("");
  const add = useSave("suppressions", () => ok(client.POST("/api/settings/suppressions", { body: { kind, value, reason: "manual" } })));
  return (
    <div className="space-y-4">
    <Card title="Do not contact">
      <p className="mb-3 text-sm text-muted">Add only. What you enter is turned into a one-way fingerprint and the fingerprint is what is kept, but a fingerprint of a guessable address can still be tested, so treat this list as sensitive.</p>
      <div className="flex flex-wrap items-end gap-2">
        <Select aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className="w-32">
          <option value="email">Address</option>
          <option value="domain">Domain</option>
        </Select>
        <Input aria-label="Value to suppress" value={value} onChange={(e) => setValue(e.target.value)} className="max-w-xs" />
        <Button
          disabled={!value.trim()}
          onClick={() =>
            add.mutate(undefined, {
              onSuccess: () => setValue(""),
            })
          }
        >
          Add
        </Button>
      </div>
      <Problem error={add.error} />
      {entries.data?.length === 0 && <Empty>Nobody is suppressed.</Empty>}
      <Table>
        <tbody>
          {entries.data?.map((e) => (
            <tr key={e.fingerprint + e.kind}>
              <Td>{e.kind}</Td>
              <Td className="font-mono text-xs">{e.fingerprint}…</Td>
              <Td>{words(e.reason)}</Td>
              <Td>{when(e.created_at)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </Card>
    <Forget />
    </div>
  );
}
