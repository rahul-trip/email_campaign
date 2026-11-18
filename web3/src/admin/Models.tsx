/** Admin → Vendors → Models: the AI models staff add, each with everything needed to call it,
 * its own key and what its calls use in AI credits; and which one is the default (and writer). */
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Callout, Card, Dialog, Field, Input, Problem, Select, Table, Td, Th } from "../ui/compat";
import { Pill } from "./bits";

type Listing = Schemas["VendorsOut"];
type Model = Schemas["LlmModelOut"];
type Provider = Schemas["LlmProviderOut"];
type ModelIn = Schemas["LlmModelIn"];

const PROVIDER_LABEL: Record<string, string> = {
  openai_compatible: "OpenAI-compatible (DeepInfra, Groq, Together, OpenRouter, vLLM…)",
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Google Gemini",
  ollama: "Ollama (on your own server)",
  github_copilot: "GitHub Copilot",
};

export function ModelsCard({ data, onSaved }: { data: Listing; onSaved: (data: unknown) => void }) {
  const [editing, setEditing] = useState<Model | "new" | "current" | null>(null);
  const [tested, setTested] = useState<Record<string, { ok: boolean | null; message: string }>>({});
  const choose = useMutation({
    mutationFn: (body: { default_model: string; writer_model: string }) => ok(client.PUT("/api/admin/models/default", { body })),
    onSuccess: onSaved,
  });
  const remove = useMutation({
    mutationFn: (code: string) => ok(client.DELETE("/api/admin/models/{code}", { params: { path: { code } } })),
    onSuccess: onSaved,
  });
  const test = useMutation({
    mutationFn: async (code: string) => ({ code, result: await ok(client.POST("/api/admin/models/{code}/test", { params: { path: { code } } })) }),
    onSuccess: ({ code, result }) => setTested((all) => ({ ...all, [code]: result })),
  });
  const { models, default_model: current, writer_model: writer } = data;
  const fallback = `${data.llm.llm_provider ?? ""} · ${data.llm.llm_model ?? ""}`;
  return (
    <Card
      tour="admin-models"
      title="AI models"
      subtitle="Every model call (research, screening, writing) uses the default model. Changing it applies from the next call; no restart."
      actions={
        <div className="flex gap-2">
          {models.length === 0 && (
            <Button size="sm" variant="secondary" onClick={() => setEditing("current")}>
              Add the current model
            </Button>
          )}
          <Button size="sm" onClick={() => setEditing("new")}>
            Add a model
          </Button>
        </div>
      }
    >
      {!current && <Callout tone="info" className="mb-3">No default chosen: the environment's settings are used ({fallback}). Add a model and make it the default to manage it here.</Callout>}
      {models.length > 0 && (
        <div className="overflow-x-auto">
          <Table>
            <thead>
              <tr>
                <Th>Model</Th>
                <Th>Provider and address</Th>
                <Th>AI credits per million tokens</Th>
                <Th>Key</Th>
                <Th />
              </tr>
            </thead>
            <tbody>
              {models.map((m) => (
                <tr key={m.code} className="align-top">
                  <Td>
                    <div className="flex flex-wrap items-center gap-1.5 font-medium">
                      {m.label}
                      {m.code === current && <Pill tone="good">default</Pill>}
                      {m.code === writer && <Pill tone="muted">writes emails</Pill>}
                    </div>
                    <div className="font-mono text-label text-muted">{m.model}</div>
                    <div className="text-label text-muted">
                      temperature {m.temperature} · max {m.max_tokens.toLocaleString()} tokens{m.reasoning_effort ? ` · reasoning ${m.reasoning_effort}` : ""}
                    </div>
                    {tested[m.code] && (
                      <div role="status" className={`mt-1 text-label ${tested[m.code]!.ok ? "text-good" : "text-error"}`}>
                        {tested[m.code]!.message}
                      </div>
                    )}
                  </Td>
                  <Td className="text-small">
                    {m.provider.replaceAll("_", " ")}
                    <div className="max-w-56 truncate font-mono text-label text-muted" title={m.base_url}>
                      {m.base_url || "the provider's own address"}
                    </div>
                  </Td>
                  <Td className="tnum text-small">
                    {m.input_credits || m.output_credits ? (
                      `${m.input_credits} in · ${m.output_credits} out`
                    ) : (
                      <span className="text-attention">not set: its calls use no credits</span>
                    )}
                  </Td>
                  <Td className="font-mono text-small">{m.key || <span className="font-sans text-muted">the Language model key</span>}</Td>
                  <Td className="space-x-1 whitespace-nowrap text-right">
                    {m.code !== current && (
                      <Button size="sm" variant="secondary" busy={choose.isPending} onClick={() => choose.mutate({ default_model: m.code, writer_model: "" })}>
                        Make default
                      </Button>
                    )}
                    {current && m.code !== current && m.code !== writer && (
                      <Button size="sm" variant="ghost" onClick={() => choose.mutate({ default_model: current, writer_model: m.code })} title="Must use the same provider and address as the default">
                        Use for writing
                      </Button>
                    )}
                    {m.code === writer && (
                      <Button size="sm" variant="ghost" onClick={() => choose.mutate({ default_model: current, writer_model: "" })}>
                        Stop writing
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" busy={test.isPending && test.variables === m.code} onClick={() => test.mutate(m.code)} title="One tiny real call to the model">
                      Test
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(m)}>
                      Edit
                    </Button>
                    {m.code !== current && m.code !== writer && (
                      <Button size="sm" variant="ghost" busy={remove.isPending && remove.variables === m.code} onClick={() => remove.mutate(m.code)}>
                        Remove
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      )}
      {current && (
        <div className="mt-3">
          <Button size="sm" variant="ghost" onClick={() => choose.mutate({ default_model: "", writer_model: "" })}>
            Go back to the environment's settings
          </Button>
        </div>
      )}
      <Problem error={choose.error ?? remove.error ?? test.error} className="mt-3" />
      {editing && (
        <ModelDialog
          model={typeof editing === "object" ? editing : null}
          start={editing === "current" ? fromCurrent(data) : undefined}
          providers={data.providers}
          taken={models.map((m) => m.code)}
          onClose={() => setEditing(null)}
          onDone={(saved) => {
            onSaved(saved);
            setEditing(null);
          }}
        />
      )}
    </Card>
  );
}

/** A starting point taken from the settings in use, so the current model is one click away. */
function fromCurrent(data: Listing): Partial<Model> {
  const llm = data.llm;
  const model = String(llm.llm_model ?? "");
  const charge = data.llm_charges.find((c) => c.model === model);
  return {
    code: model.split("/").pop()?.toLowerCase().replace(/[^a-z0-9._-]/g, "-") ?? "",
    label: model,
    provider: String(llm.llm_provider ?? "openai_compatible"),
    model,
    base_url: String(llm.llm_base_url ?? ""),
    temperature: Number(llm.llm_temperature ?? 0.7),
    max_tokens: Number(llm.llm_max_tokens ?? 4000),
    input_credits: charge?.per_million_input ?? 0,
    output_credits: charge?.per_million_output ?? 0,
  };
}

function ModelDialog({
  model,
  start,
  providers,
  taken,
  onClose,
  onDone,
}: {
  model: Model | null;
  start?: Partial<Model>;
  providers: Provider[];
  taken: string[];
  onClose: () => void;
  onDone: (data: unknown) => void;
}) {
  const from = model ?? start ?? {};
  const [code, setCode] = useState(from.code ?? "");
  const [label, setLabel] = useState(from.label ?? "");
  const [provider, setProvider] = useState(from.provider ?? "openai_compatible");
  const [name, setName] = useState(from.model ?? "");
  const [baseUrl, setBaseUrl] = useState(from.base_url ?? "");
  const [key, setKey] = useState("");
  const [removeKey, setRemoveKey] = useState(false);
  const [temperature, setTemperature] = useState(String(from.temperature ?? 0.7));
  const [maxTokens, setMaxTokens] = useState(String(from.max_tokens ?? 4000));
  const [effort, setEffort] = useState(from.reasoning_effort ?? "");
  const [input, setInput] = useState(String(from.input_credits ?? ""));
  const [output, setOutput] = useState(String(from.output_credits ?? ""));
  const preset = providers.find((p) => p.code === provider);
  const clash = !model && taken.includes(code.trim());
  const ready = code.trim() && label.trim() && name.trim() && !clash && (!preset?.needs_base_url || baseUrl.trim());
  const save = useMutation({
    mutationFn: () => {
      const body: ModelIn = {
        label: label.trim(),
        provider: provider as ModelIn["provider"],
        model: name.trim(),
        base_url: baseUrl.trim(),
        temperature: Number(temperature),
        max_tokens: Math.round(Number(maxTokens)),
        reasoning_effort: effort as ModelIn["reasoning_effort"],
        input_credits: Number(input || 0),
        output_credits: Number(output || 0),
        api_key: removeKey ? "" : key.trim() ? key.trim() : null,
      };
      return ok(client.PUT("/api/admin/models/{code}", { params: { path: { code: code.trim() } }, body }));
    },
    onSuccess: onDone,
  });
  return (
    <Dialog
      title={model ? `Edit ${model.label}` : "Add a model"}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={save.isPending} disabled={!ready} onClick={() => save.mutate()}>
            Save model
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name shown here">
          <Input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="DeepSeek V3 on DeepInfra" className="w-full" />
        </Field>
        <Field label="Code" hint={model ? "Fixed." : clash ? "Already used." : "Letters, digits, . - _"}>
          <Input value={code} disabled={Boolean(model)} onChange={(e) => setCode(e.target.value)} placeholder="deepseek-v3" className="w-full font-mono" />
        </Field>
      </div>
      <Field label="Provider type" hint="How the engine talks to it. Most hosted open models use the OpenAI-compatible type with the host's base URL.">
        <Select value={provider} onChange={(e) => setProvider(e.target.value)} className="w-full">
          {providers.map((p) => (
            <option key={p.code} value={p.code}>
              {PROVIDER_LABEL[p.code] ?? p.code}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Model name at the provider" hint="Exactly as the provider spells it.">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="deepseek-ai/DeepSeek-V3" className="w-full font-mono" />
      </Field>
      <Field label={preset?.needs_base_url ? "Base URL (required)" : "Base URL"} hint={preset?.needs_base_url ? "The OpenAI-compatible endpoint, ending before /chat/completions." : `Empty: ${preset?.default_base_url || "the provider's own address"}. Set it only for a proxy.`}>
        <Input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={preset?.default_base_url || "https://api.deepinfra.com/v1/openai"} className="w-full font-mono" />
      </Field>
      <Field
        label="API key"
        hint={
          preset?.needs_key === false
            ? "This provider needs no key."
            : model?.key
              ? `Stored (${model.key}). Leave empty to keep it.`
              : "Stored encrypted and never shown again. Empty: the Language model vendor key above is used."
        }
      >
        <Input type="password" autoComplete="off" value={key} disabled={removeKey} onChange={(e) => setKey(e.target.value)} className="w-full font-mono" />
      </Field>
      {model?.key && (
        <label className="flex items-center gap-2 text-small">
          <input type="checkbox" checked={removeKey} onChange={(e) => setRemoveKey(e.target.checked)} className="accent-[var(--primary)]" />
          Remove its own key (use the Language model vendor key)
        </label>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Temperature" hint="0 to 2">
          <Input type="number" min={0} max={2} step="0.1" value={temperature} onChange={(e) => setTemperature(e.target.value)} className="w-full" />
        </Field>
        <Field label="Max tokens" hint="Reasoning models need room">
          <Input type="number" min={16} max={200000} step="500" value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} className="w-full" />
        </Field>
        <Field label="Reasoning effort" hint="Only for models that think">
          <Select value={effort} onChange={(e) => setEffort(e.target.value)} className="w-full">
            <option value="">none</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
          </Select>
        </Field>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="AI credits per million input tokens" hint="What it reads">
          <Input type="number" min={0} step="1" value={input} onChange={(e) => setInput(e.target.value)} className="w-full" />
        </Field>
        <Field label="AI credits per million output tokens" hint="What it writes">
          <Input type="number" min={0} step="1" value={output} onChange={(e) => setOutput(e.target.value)} className="w-full" />
        </Field>
      </div>
      {!Number(input) && !Number(output) && <Callout tone="attention">With no charge, this model's calls use no AI credits.</Callout>}
      <Problem error={save.error} />
    </Dialog>
  );
}
