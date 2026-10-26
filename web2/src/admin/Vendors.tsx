import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Callout, Card, Dialog, Field, Input, PageHeader, Problem, QueryState, Table, Td, Th } from "../components/ui";
import { Pill, When } from "./bits";

type Vendor = Schemas["VendorOut"];
const path = (vendor: string) => ({ params: { path: { vendor } } });

export function VendorsPage() {
  const queryClient = useQueryClient();
  const vendors = useQuery({ queryKey: ["admin", "vendors"], queryFn: () => ok(client.GET("/api/admin/vendors")) });
  const [replacing, setReplacing] = useState<Vendor | null>(null);
  const [revealed, setRevealed] = useState<{ vendor: Vendor; key: string } | null>(null);
  const refresh = (data: unknown) => queryClient.setQueryData(["admin", "vendors"], data);
  const rollback = useMutation({ mutationFn: (v: Vendor) => ok(client.POST("/api/admin/vendors/{vendor}/rollback", path(v.code))), onSuccess: refresh });
  const pause = useMutation({
    mutationFn: (v: Vendor) => ok(client.PUT("/api/admin/vendors/{vendor}/paused", { ...path(v.code), body: { paused: !v.paused } })),
    onSuccess: refresh,
  });
  const reveal = useMutation({
    mutationFn: async (v: Vendor) => ({ vendor: v, key: (await ok(client.POST("/api/admin/vendors/{vendor}/reveal", path(v.code)))).key }),
    onSuccess: setRevealed,
  });
  return (
    <>
      <PageHeader title="Vendors and keys" subtitle="The third-party services the platform pays for. A new key reaches the worker on its next run; no restart." />
      <Problem error={rollback.error ?? pause.error ?? reveal.error} className="mb-3" />
      <QueryState query={vendors} rows={6}>
        {(data) => (
          <div className="space-y-4">
            <div className="overflow-x-auto rounded-xl border border-line bg-surface" data-tour="admin-vendors">
              <Table>
                <thead>
                  <tr>
                    <Th>Vendor</Th>
                    <Th>Does</Th>
                    <Th>Key</Th>
                    <Th>Set</Th>
                    <Th>Status</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {data.vendors.map((v) => (
                    <tr key={v.code}>
                      <Td className="font-medium">{v.name}</Td>
                      <Td className="text-muted">{v.role}</Td>
                      <Td className="font-mono text-xs">
                        {v.key}
                        {v.source === "environment" && <span className="ml-2 text-[11px] text-muted">from the environment</span>}
                      </Td>
                      <Td className="text-muted">{v.set_at ? <When iso={v.set_at} time /> : "—"}</Td>
                      <Td>{v.paused ? <Pill tone="error">paused</Pill> : v.source === "none" ? <Pill tone="muted">off</Pill> : <Pill tone="good">live</Pill>}</Td>
                      <Td className="space-x-1 text-right whitespace-nowrap">
                        <Button size="sm" variant="secondary" onClick={() => setReplacing(v)}>
                          {v.source === "database" ? "Replace" : "Add key"}
                        </Button>
                        {v.source === "database" && (
                          <Button size="sm" variant="ghost" busy={reveal.isPending && reveal.variables?.code === v.code} onClick={() => reveal.mutate(v)}>
                            Reveal
                          </Button>
                        )}
                        {v.can_roll_back && (
                          <Button size="sm" variant="ghost" onClick={() => rollback.mutate(v)}>
                            Roll back
                          </Button>
                        )}
                        {v.source !== "none" && (
                          <Button size="sm" variant="ghost" onClick={() => pause.mutate(v)}>
                            {v.paused ? "Resume" : "Pause"}
                          </Button>
                        )}
                      </Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
            <LlmCard llm={data.llm} onSaved={refresh} />
          </div>
        )}
      </QueryState>
      {replacing && <ReplaceKey vendor={replacing} onClose={() => setReplacing(null)} onDone={(data) => { refresh(data); setReplacing(null); }} />}
      {revealed && (
        <Dialog title={`${revealed.vendor.name} key`} onClose={() => setRevealed(null)} footer={<Button onClick={() => setRevealed(null)}>Done</Button>}>
          <Callout tone="attention">This view is recorded in the audit log.</Callout>
          <code className="block break-all rounded-lg bg-surface-low p-3 font-mono text-xs">{revealed.key}</code>
        </Dialog>
      )}
    </>
  );
}

function ReplaceKey({ vendor, onClose, onDone }: { vendor: Vendor; onClose: () => void; onDone: (data: unknown) => void }) {
  const [key, setKey] = useState("");
  const save = useMutation({
    mutationFn: () => ok(client.PUT("/api/admin/vendors/{vendor}/key", { ...path(vendor.code), body: { key } })),
    onSuccess: onDone,
  });
  return (
    <Dialog
      title={`${vendor.source === "database" ? "Replace" : "Add"} the ${vendor.name} key`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={save.isPending} disabled={key.trim().length < 8} onClick={() => save.mutate()}>
            Save key
          </Button>
        </>
      }
    >
      <Field label="New key" hint="Stored encrypted. The previous key is kept for 30 days so you can roll back.">
        <Input type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} className="w-full" />
      </Field>
      <Problem error={save.error} />
    </Dialog>
  );
}

const LLM_LABELS: [string, string][] = [
  ["llm_provider", "Provider"],
  ["llm_base_url", "Base URL"],
  ["llm_model", "Model"],
  ["llm_copy_model", "Writer model (blank: same)"],
  ["llm_temperature", "Temperature"],
  ["llm_max_tokens", "Max tokens"],
];

function LlmCard({ llm, onSaved }: { llm: Record<string, string | number>; onSaved: (data: unknown) => void }) {
  const [form, setForm] = useState<Record<string, string>>(Object.fromEntries(Object.entries(llm).map(([k, v]) => [k, String(v)])));
  const save = useMutation({
    mutationFn: () =>
      ok(
        client.PATCH("/api/admin/vendors/llm", {
          body: {
            llm_provider: form.llm_provider,
            llm_base_url: form.llm_base_url,
            llm_model: form.llm_model,
            llm_copy_model: form.llm_copy_model,
            llm_temperature: Number(form.llm_temperature),
            llm_max_tokens: Number(form.llm_max_tokens),
          },
        }),
      ),
    onSuccess: onSaved,
  });
  return (
    <Card title="Language model" subtitle="DeepSeek on DeepInfra uses the OpenAI-compatible provider. The key is the Language model row above.">
      <div className="grid gap-3 sm:grid-cols-2">
        {LLM_LABELS.map(([name, label]) => (
          <Field key={name} label={label}>
            <Input value={form[name] ?? ""} onChange={(e) => setForm({ ...form, [name]: e.target.value })} className="w-full" />
          </Field>
        ))}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <Button busy={save.isPending} onClick={() => save.mutate()}>
          Save
        </Button>
        {save.isSuccess && <span className="text-xs text-muted">Saved. The worker uses it on its next run.</span>}
      </div>
      <Problem error={save.error} className="mt-3" />
    </Card>
  );
}
