import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Badge, Button, Card, Empty, Field, Input, Problem, Select, Table, Td, Th, Textarea, when, words } from "../components/ui";

type Tab = "sender" | "workspace" | "campaigns" | "policies" | "suppressions" | "mailboxes";
const TABS: [Tab, string][] = [
  ["sender", "Sender profile"],
  ["workspace", "Limits"],
  ["campaigns", "Campaigns"],
  ["policies", "Country policies"],
  ["suppressions", "Do not contact"],
  ["mailboxes", "Mailboxes"],
];

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

function useSave<T>(key: string, send: (value: T) => Promise<unknown>) {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: send, onSuccess: () => queryClient.invalidateQueries({ queryKey: [key] }) });
}

// ---------------------------------------------------------------- sender profile

const SCALARS: [string, string, string?][] = [
  ["company_name", "Company name"],
  ["legal_name", "Legal name", "Printed in every footer."],
  ["postal_address", "Postal address", "Required by the US, EU and Canadian footers."],
  ["registration_details", "Registration details", "Company number, for the UK footer."],
  ["contact_info", "Contact details", "Used in the Canadian footer."],
  ["signature_name", "Signature: your name"],
  ["signature_title", "Signature: your title"],
  ["domain", "Website"],
  ["industry", "Industry"],
  ["mission", "Mission"],
  ["geographic_focus", "Where you sell"],
];
const LISTS: [string, string][] = [
  ["value_propositions", "Value propositions (one per line)"],
  ["technologies", "Technologies (one per line)"],
  ["case_studies", "Proof points (one per line)"],
  ["target_verticals", "Target verticals (one per line)"],
];

function SenderProfile() {
  const profile = useQuery({ queryKey: ["sender"], queryFn: () => ok(client.GET("/api/settings/sender-profile")) });
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  useEffect(() => {
    if (profile.data) setDraft(profile.data as Record<string, unknown>);
  }, [profile.data]);
  const save = useSave("sender", () => ok(client.PUT("/api/settings/sender-profile", { body: draft })));
  const text = (key: string) => String(draft[key] ?? "");
  const list = (key: string) => ((draft[key] as string[] | undefined) ?? []).join("\n");
  return (
    <Card title="Sender profile" actions={<Button onClick={() => save.mutate(undefined)}>Save</Button>}>
      <div className="grid gap-3 sm:grid-cols-2">
        {SCALARS.map(([key, label, hint]) => (
          <Field key={key} label={label} hint={hint}>
            <Input value={text(key)} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
          </Field>
        ))}
        {LISTS.map(([key, label]) => (
          <Field key={key} label={label}>
            <Textarea rows={4} value={list(key)} onChange={(e) => setDraft({ ...draft, [key]: lines(e.target.value) })} />
          </Field>
        ))}
        <div className="sm:col-span-2">
          <Field label="About you (the copywriter reads this)">
            <Textarea rows={8} value={text("narrative")} onChange={(e) => setDraft({ ...draft, narrative: e.target.value })} />
          </Field>
        </div>
      </div>
      <Problem error={save.error} />
      {save.isSuccess && <p className="mt-2 text-sm text-green-700">Saved.</p>}
    </Card>
  );
}

// ---------------------------------------------------------------- limits

function Limits() {
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const [safe, setSafe] = useState(true);
  const [budget, setBudget] = useState("0.50");
  const [examples, setExamples] = useState(5);
  useEffect(() => {
    const s = settings.data;
    if (!s) return;
    setSafe(Boolean(s.safe_to_send_only));
    setBudget((Number(s.budget_per_prospect_micro_usd ?? 0) / 1_000_000).toFixed(2));
    setExamples(Number(s.few_shot_examples ?? 5));
  }, [settings.data]);
  const save = useSave("workspace-settings", () =>
    ok(
      client.PUT("/api/settings/workspace", {
        body: { safe_to_send_only: safe, budget_per_prospect_micro_usd: Math.round(Number(budget) * 1_000_000), few_shot_examples: examples },
      }),
    ),
  );
  return (
    <Card title="Limits" actions={<Button onClick={() => save.mutate(undefined)}>Save</Button>}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Budget per prospect (USD)" hint="No paid call is made once a lead has spent this.">
          <Input type="number" step="0.01" min="0" value={budget} onChange={(e) => setBudget(e.target.value)} />
        </Field>
        <Field label="Earlier edits shown to the writer" hint="Your last N corrected emails in the campaign.">
          <Input type="number" min={0} max={20} value={examples} onChange={(e) => setExamples(Number(e.target.value))} />
        </Field>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={safe} onChange={(e) => setSafe(e.target.checked)} />
          <span>
            <strong>Only send to proven addresses</strong>
            <span className="block text-xs text-muted">Catch-all addresses that could not be proven are held.</span>
          </span>
        </label>
      </div>
      <p className="mt-3 text-xs text-muted">Automatic sending is off, and cannot be switched on until the later send phase.</p>
      <Problem error={save.error} />
      {save.isSuccess && <p className="mt-2 text-sm text-green-700">Saved.</p>}
    </Card>
  );
}

// ---------------------------------------------------------------- campaigns

function CampaignForm({ campaign, onSaved }: { campaign?: Schemas["CampaignOut"]; onSaved: () => void }) {
  const [name, setName] = useState(campaign?.name ?? "");
  const [titles, setTitles] = useState((campaign?.target_titles ?? []).join("\n"));
  const [icp, setIcp] = useState(campaign?.icp_description ?? "");
  const [minFit, setMinFit] = useState(campaign?.min_fit_score ?? 60);
  const [questions, setQuestions] = useState((campaign?.research_questions ?? []).join("\n"));
  const [cadence, setCadence] = useState((campaign?.cadence_days ?? [0, 3, 8]).join(", "));
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name,
        target_titles: lines(titles),
        icp_description: icp || null,
        min_fit_score: minFit,
        research_questions: lines(questions),
        cadence_days: cadence.split(",").map((n) => Number(n.trim())).filter((n) => !Number.isNaN(n)),
      };
      return campaign
        ? ok(client.PATCH("/api/settings/campaigns/{campaign_id}", { params: { path: { campaign_id: campaign.id } }, body }))
        : ok(client.POST("/api/settings/campaigns", { body }));
    },
    onSuccess: onSaved,
  });
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Field label="Name">
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label="Minimum fit score (0–100)" hint="Hand-picked targets skip this.">
        <Input type="number" min={0} max={100} value={minFit} onChange={(e) => setMinFit(Number(e.target.value))} />
      </Field>
      <Field label="Wanted job titles (one per line, best first)">
        <Textarea rows={4} value={titles} onChange={(e) => setTitles(e.target.value)} />
      </Field>
      <Field label="Research questions (up to 3, one per line)">
        <Textarea rows={4} value={questions} onChange={(e) => setQuestions(e.target.value)} />
      </Field>
      <div className="sm:col-span-2">
        <Field label="Ideal customer">
          <Textarea rows={3} value={icp} onChange={(e) => setIcp(e.target.value)} />
        </Field>
      </div>
      <Field label="Follow-up days after the first email" hint="Comma separated, for example 0, 3, 8">
        <Input value={cadence} onChange={(e) => setCadence(e.target.value)} />
      </Field>
      <div className="flex items-end">
        <Button onClick={() => save.mutate()} disabled={!name.trim() || save.isPending}>
          {campaign ? "Save campaign" : "Create campaign"}
        </Button>
      </div>
      <div className="sm:col-span-2">
        <Problem error={save.error} />
      </div>
    </div>
  );
}

function Campaigns() {
  const queryClient = useQueryClient();
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  const saved = () => void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
  return (
    <div className="space-y-4">
      {campaigns.data?.map((c) => (
        <Card key={c.id} title={c.name}>
          <CampaignForm campaign={c} onSaved={saved} />
        </Card>
      ))}
      <Card title="New campaign">
        <CampaignForm key={campaigns.data?.length} onSaved={saved} />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- policies

const RULES = ["allow", "allow_with_footer", "consent_required", "block"] as const;

function PolicyRow({ policy }: { policy: Schemas["PolicyOut"] }) {
  const [rule, setRule] = useState<(typeof RULES)[number]>(policy.rule);
  const [corporate, setCorporate] = useState(policy.requires_corporate_subscriber);
  const [footer, setFooter] = useState(policy.footer_template ?? "");
  const [reviewer, setReviewer] = useState(policy.reviewed_by ?? "");
  const save = useSave("policies", () =>
    ok(
      client.PUT("/api/settings/policies/{country_code}", {
        params: { path: { country_code: policy.country_code } },
        body: { rule, requires_corporate_subscriber: corporate, allowed_provenance: policy.allowed_provenance, footer_template: footer || null, reviewed_by: reviewer || null },
      }),
    ),
  );
  return (
    <tr>
      <Td className="font-semibold">{policy.country_code}</Td>
      <Td>
        <Select aria-label={`Rule for ${policy.country_code}`} value={rule} onChange={(e) => setRule(e.target.value as typeof rule)}>
          {RULES.map((r) => (
            <option key={r} value={r}>
              {words(r)}
            </option>
          ))}
        </Select>
        <label className="mt-1 flex items-center gap-1 text-xs">
          <input type="checkbox" checked={corporate} onChange={(e) => setCorporate(e.target.checked)} /> companies only
        </label>
      </Td>
      <Td>
        <Textarea rows={3} aria-label={`Footer for ${policy.country_code}`} value={footer} onChange={(e) => setFooter(e.target.value)} />
      </Td>
      <Td>
        <Input aria-label={`Reviewer for ${policy.country_code}`} placeholder="Who checked this?" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        <span className="text-xs text-muted">v{policy.version}</span>
      </Td>
      <Td>
        <Button variant="secondary" onClick={() => save.mutate(undefined)}>
          Save
        </Button>
        <Problem error={save.error} />
      </Td>
    </tr>
  );
}

function Policies() {
  const policies = useQuery({ queryKey: ["policies"], queryFn: () => ok(client.GET("/api/settings/policies")) });
  const [code, setCode] = useState("");
  const add = useSave("policies", () =>
    ok(client.PUT("/api/settings/policies/{country_code}", { params: { path: { country_code: code } }, body: { rule: "block" } })),
  );
  return (
    <Card title="Country policies">
      <p className="mb-3 text-sm text-muted">
        These are working defaults, not legal advice. Have them reviewed, and record who did, before turning on automatic sending. Every change raises the version, and each decision records the version it used.
      </p>
      <Table>
        <thead>
          <tr>
            <Th>Country</Th>
            <Th>Rule</Th>
            <Th>Footer</Th>
            <Th>Review</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {policies.data?.map((p) => (
            <PolicyRow key={`${p.country_code}-${p.version}`} policy={p} />
          ))}
        </tbody>
      </Table>
      <div className="mt-3 flex items-end gap-2">
        <Field label="Add a country (two letters)">
          <Input value={code} maxLength={2} onChange={(e) => setCode(e.target.value.toUpperCase())} className="w-24" />
        </Field>
        <Button variant="secondary" disabled={code.length !== 2} onClick={() => add.mutate(undefined)}>
          Add as blocked
        </Button>
      </div>
      <Problem error={add.error} />
    </Card>
  );
}

// ---------------------------------------------------------------- suppressions

function Suppressions() {
  const entries = useQuery({ queryKey: ["suppressions"], queryFn: () => ok(client.GET("/api/settings/suppressions")) });
  const [kind, setKind] = useState<"email" | "domain">("email");
  const [value, setValue] = useState("");
  const add = useSave("suppressions", () => ok(client.POST("/api/settings/suppressions", { body: { kind, value, reason: "manual" } })));
  return (
    <Card title="Do not contact">
      <p className="mb-3 text-sm text-muted">Add only. Values are turned into a fingerprint when saved; the address itself is never stored.</p>
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
  );
}

// ---------------------------------------------------------------- mailboxes

function Mailboxes() {
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

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>("sender");
  return (
    <div className="space-y-4">
      <div role="tablist" className="flex flex-wrap gap-1">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`rounded-md px-3 py-1.5 text-sm ${tab === id ? "bg-brand text-white" : "bg-white hover:bg-gray-100"}`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "sender" && <SenderProfile />}
      {tab === "workspace" && <Limits />}
      {tab === "campaigns" && <Campaigns />}
      {tab === "policies" && <Policies />}
      {tab === "suppressions" && <Suppressions />}
      {tab === "mailboxes" && <Mailboxes />}
    </div>
  );
}
