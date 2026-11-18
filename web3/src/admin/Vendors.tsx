import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Callout, Card, Dialog, Field, Input, PageHeader, Problem, QueryState, Table, Td, Th } from "../ui/compat";
import { Pill, When } from "./bits";

type Vendor = Schemas["VendorOut"];
type Slot = { vendor: Vendor; slot: number };
const MAX_KEYS = 3;
const path = (vendor: string) => ({ params: { path: { vendor } } });
const inSlot = (vendor: string, slot: number) => ({ params: { path: { vendor }, query: { slot } } });
const freeSlot = (v: Vendor) => [1, 2, 3].find((n) => !v.keys.some((k) => k.slot === n)) ?? 1;

export function VendorsPage() {
  const queryClient = useQueryClient();
  const vendors = useQuery({ queryKey: ["admin", "vendors"], queryFn: () => ok(client.GET("/api/admin/vendors")) });
  const [replacing, setReplacing] = useState<Slot | null>(null);
  const [tested, setTested] = useState<Record<string, { ok: boolean | null; message: string }>>({});
  const test = useMutation({
    mutationFn: async ({ vendor, slot }: Slot) => ({
      id: `${vendor.code}:${slot}`,
      result: await ok(client.POST("/api/admin/vendors/{vendor}/test", inSlot(vendor.code, slot))),
    }),
    onSuccess: ({ id, result }) => setTested((all) => ({ ...all, [id]: result })),
  });
  const [capping, setCapping] = useState<Vendor | null>(null);
  const [revealed, setRevealed] = useState<{ vendor: Vendor; slot: number; key: string } | null>(null);
  const refresh = (data: unknown) => queryClient.setQueryData(["admin", "vendors"], data);
  const rollback = useMutation({ mutationFn: ({ vendor, slot }: Slot) => ok(client.POST("/api/admin/vendors/{vendor}/rollback", inSlot(vendor.code, slot))), onSuccess: refresh });
  const remove = useMutation({
    mutationFn: ({ vendor, slot }: Slot) => ok(client.DELETE("/api/admin/vendors/{vendor}/key", inSlot(vendor.code, slot))),
    onSuccess: refresh,
  });
  const pause = useMutation({
    mutationFn: (v: Vendor) => ok(client.PUT("/api/admin/vendors/{vendor}/paused", { ...path(v.code), body: { paused: !v.paused } })),
    onSuccess: refresh,
  });
  const reveal = useMutation({
    mutationFn: async ({ vendor, slot }: Slot) => ({ vendor, slot, key: (await ok(client.POST("/api/admin/vendors/{vendor}/reveal", inSlot(vendor.code, slot)))).key }),
    onSuccess: setRevealed,
  });
  const busy = (m: { isPending: boolean; variables?: Slot }, v: Vendor, slot: number) => m.isPending && m.variables?.vendor.code === v.code && m.variables.slot === slot;
  const result = (v: Vendor, slot: number) => {
    const r = tested[`${v.code}:${slot}`];
    return r ? (
      <div role="status" className={`mt-1 max-w-64 text-label ${r.ok === false ? "text-error" : r.ok ? "text-good" : "text-muted"}`}>
        {r.message}
      </div>
    ) : null;
  };
  return (
    <>
      <PageHeader
        title="Vendors and keys"
        subtitle="The third-party services the platform pays for. A vendor can have up to three keys: each call uses one at random and skips a key that is refused or out of credit. A new key reaches the worker on its next run; no restart."
      />
      <Problem error={rollback.error ?? remove.error ?? pause.error ?? reveal.error ?? test.error} className="mb-3" />
      <QueryState query={vendors} rows={6} shape="table">
        {(data) => (
          <div className="space-y-4">
            <div className="overflow-x-auto rounded-xl border border-line bg-surface" data-tour="admin-vendors">
              <Table>
                <thead>
                  <tr>
                    <Th>Vendor</Th>
                    <Th>Does</Th>
                    <Th>Keys</Th>
                    <Th>Spend this month</Th>
                    <Th>Status</Th>
                    <Th />
                  </tr>
                </thead>
                <tbody>
                  {data.vendors.map((v) => (
                    <tr key={v.code} className="align-top">
                      <Td className="font-medium">{v.name}</Td>
                      <Td className="text-muted">{v.role}</Td>
                      <Td className="text-small">
                        {v.keys.length === 0 ? (
                          <div>
                            <span className="font-mono">{v.key}</span>
                            {v.source === "environment" && <span className="ml-2 text-label text-muted">from the environment</span>}
                            {v.source === "environment" && v.can_test && (
                              <Button size="sm" variant="ghost" className="ml-1" busy={busy(test, v, 1)} onClick={() => test.mutate({ vendor: v, slot: 1 })} title="Makes one small real call (a fraction of a cent) to check the key works">
                                Test
                              </Button>
                            )}
                            {result(v, 1)}
                          </div>
                        ) : (
                          <ul className="space-y-1">
                            {v.keys.map((k) => (
                              <li key={k.slot}>
                                <div className="flex flex-wrap items-center gap-1 whitespace-nowrap">
                                  <span className="font-mono">{k.key}</span>
                                  <span className="text-label text-muted">
                                    key {k.slot} · <When iso={k.set_at} />
                                  </span>
                                  <Button size="sm" variant="ghost" onClick={() => setReplacing({ vendor: v, slot: k.slot })}>
                                    Replace
                                  </Button>
                                  {v.can_test && (
                                    <Button size="sm" variant="ghost" busy={busy(test, v, k.slot)} onClick={() => test.mutate({ vendor: v, slot: k.slot })} title="Makes one small real call (a fraction of a cent) to check the key works">
                                      Test
                                    </Button>
                                  )}
                                  <Button size="sm" variant="ghost" busy={busy(reveal, v, k.slot)} onClick={() => reveal.mutate({ vendor: v, slot: k.slot })}>
                                    Reveal
                                  </Button>
                                  {k.can_roll_back && (
                                    <Button size="sm" variant="ghost" onClick={() => rollback.mutate({ vendor: v, slot: k.slot })}>
                                      Roll back
                                    </Button>
                                  )}
                                  <Button size="sm" variant="ghost" busy={busy(remove, v, k.slot)} onClick={() => remove.mutate({ vendor: v, slot: k.slot })} title="Stops using this key. It can be rolled back for 30 days.">
                                    Remove
                                  </Button>
                                </div>
                                {result(v, k.slot)}
                              </li>
                            ))}
                          </ul>
                        )}
                      </Td>
                      <Td className="whitespace-nowrap text-small">
                        ${(v.spend_micro_usd / 1e6).toFixed(2)}
                        {v.cap_micro_usd != null ? ` of $${(v.cap_micro_usd / 1e6).toFixed(0)}` : ""}
                        <button type="button" className="ml-2 text-primary hover:underline" onClick={() => setCapping(v)}>
                          {v.cap_micro_usd != null ? "Change cap" : "Set cap"}
                        </button>
                      </Td>
                      <Td>
                        {v.paused ? <Pill tone="error">paused</Pill> : v.source === "none" ? <Pill tone="muted">off</Pill> : v.key_refusals >= 3 ? <Pill tone="error">key refused</Pill> : <Pill tone="good">live</Pill>}
                        {v.key_refusals > 0 && <div className="mt-1 text-label text-error">refused {v.key_refusals}× in the last day</div>}
                      </Td>
                      <Td className="space-x-1 text-right whitespace-nowrap">
                        {v.keys.length < MAX_KEYS && (
                          <Button size="sm" variant="secondary" onClick={() => setReplacing({ vendor: v, slot: freeSlot(v) })}>
                            Add key
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
      {replacing && <ReplaceKey target={replacing} onClose={() => setReplacing(null)} onDone={(data) => { refresh(data); setReplacing(null); }} />}
      {capping && <CapDialog vendor={capping} onClose={() => setCapping(null)} onDone={(data) => { refresh(data); setCapping(null); }} />}
      {revealed && (
        <Dialog title={`${revealed.vendor.name} key ${revealed.slot}`} onClose={() => setRevealed(null)} footer={<Button onClick={() => setRevealed(null)}>Done</Button>}>
          <Callout tone="attention">This view is recorded in the audit log.</Callout>
          <code className="block break-all rounded-lg bg-surface-2 p-3 font-mono text-small">{revealed.key}</code>
        </Dialog>
      )}
    </>
  );
}

function ReplaceKey({ target, onClose, onDone }: { target: Slot; onClose: () => void; onDone: (data: unknown) => void }) {
  const { vendor, slot } = target;
  const [key, setKey] = useState("");
  const save = useMutation({
    mutationFn: () => ok(client.PUT("/api/admin/vendors/{vendor}/key", { ...inSlot(vendor.code, slot), body: { key } })),
    onSuccess: onDone,
  });
  const exists = vendor.keys.some((k) => k.slot === slot);
  return (
    <Dialog
      title={`${exists ? "Replace" : "Add"} ${vendor.name} key ${slot}`}
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
        {save.isSuccess && <span className="text-small text-muted">Saved. The worker uses it on its next run.</span>}
      </div>
      <Problem error={save.error} className="mt-3" />
    </Card>
  );
}

function CapDialog({ vendor, onClose, onDone }: { vendor: Vendor; onClose: () => void; onDone: (data: unknown) => void }) {
  const [dollars, setDollars] = useState(vendor.cap_micro_usd == null ? "" : String(vendor.cap_micro_usd / 1e6));
  const save = useMutation({
    mutationFn: () => ok(client.PUT("/api/admin/vendors/{vendor}/cap", { ...path(vendor.code), body: { cap_micro_usd: dollars.trim() === "" ? null : Math.round(Number(dollars) * 1e6) } })),
    onSuccess: onDone,
  });
  return (
    <Dialog
      title={`Monthly cap for ${vendor.name}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={save.isPending} onClick={() => save.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <Field label="Cap in US dollars" hint="When this month's spend reaches it, the vendor is paused and staff are emailed. Empty: no cap.">
        <Input type="number" min={0} step="1" value={dollars} onChange={(e) => setDollars(e.target.value)} className="w-40" />
      </Field>
      <Problem error={save.error} />
    </Dialog>
  );
}
