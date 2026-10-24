import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { AlertTriangle, ArrowRight, CheckCircle2, Circle, Lock } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { client, ok } from "../api/client";
import { Button, Callout, Card, Checkbox, Field, Input, Label, PageHeader, QueryState, SaveNote, Segmented, Select, Tabs, Textarea } from "../components/ui";
import { lines, when } from "../lib/format";
import { Mailboxes } from "./Mailboxes";
import { Integrations } from "./SettingsIntegrations";
import { Account, Team } from "./SettingsTeam";
import type { SettingsTab } from "./settingsTabs";

type Tab = SettingsTab;
type Profile = Record<string, unknown>;

export function SettingsPage() {
  const { tab = "setup" } = useSearch({ from: "/settings" });
  const navigate = useNavigate();
  const setTab = (next: Tab) => void navigate({ to: "/settings", search: { tab: next === "setup" ? undefined : next }, replace: true });
  return (
    <>
      <PageHeader title="Settings" subtitle="Who you are in every email, the limits the engine works within, and who works here." />
      <Tabs
        label="Settings"
        tour="settings-tabs"
        value={tab}
        onChange={setTab}
        tabs={[
          ["setup", "Setup check"],
          ["profile", "Sender profile"],
          ["mailboxes", "Mailboxes"],
          ["limits", "Limits and budget"],
          ["team", "Team"],
          ["integrations", "Integrations"],
          ["account", "Your account"],
        ]}
      >
        {tab === "setup" && <Setup onOpen={setTab} />}
        {tab === "profile" && <SenderProfile />}
        {tab === "mailboxes" && <Mailboxes />}
        {tab === "limits" && <Limits />}
        {tab === "team" && <Team />}
        {tab === "integrations" && <Integrations />}
        {tab === "account" && <Account />}
      </Tabs>
    </>
  );
}

// ------------------------------------------------------------------ setup check

/** What is missing before the engine can work well, built from what is saved. */
function Setup({ onOpen }: { onOpen: (tab: Tab) => void }) {
  const profile = useQuery({ queryKey: ["sender"], queryFn: () => ok(client.GET("/api/settings/sender-profile")) });
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  const mailboxes = useQuery({ queryKey: ["mailboxes"], queryFn: () => ok(client.GET("/api/mailboxes")) });
  const policies = useQuery({ queryKey: ["policies"], queryFn: () => ok(client.GET("/api/settings/policies")) });
  const p = (profile.data ?? {}) as Profile;
  const filled = (key: string) => String(p[key] ?? "").trim() !== "";
  const ready = campaigns.data?.find((c) => c.target_titles.length > 0 && c.icp_description);
  const allowing = (policies.data ?? []).filter((x) => x.rule !== "block");
  const unreviewed = allowing.filter((x) => !x.reviewed_by);
  const checked = (mailboxes.data ?? []).some((m) => m.dns_check);
  const loading = profile.isPending || campaigns.isPending || mailboxes.isPending || policies.isPending;

  const items: { ok: boolean; title: string; detail: string; action: ReactNode; required?: boolean }[] = [
    {
      ok: Boolean(p.reviewed_at),
      required: true,
      title: "Sender profile confirmed",
      detail: p.reviewed_at ? `Confirmed ${when(String(p.reviewed_at))}.` : "No emails are written until you have read the profile and saved it.",
      action: <Button size="sm" variant="secondary" onClick={() => onOpen("profile")}>Open profile</Button>,
    },
    {
      ok: filled("legal_name") && filled("postal_address"),
      required: true,
      title: "Legal name and postal address",
      detail: "Every country footer prints them; a footer with a gap stops the email being written.",
      action: <Button size="sm" variant="secondary" onClick={() => onOpen("profile")}>Fill in</Button>,
    },
    {
      ok: filled("signature_name"),
      required: true,
      title: "Signature",
      detail: "Your name ends every email.",
      action: <Button size="sm" variant="secondary" onClick={() => onOpen("profile")}>Fill in</Button>,
    },
    {
      ok: Boolean(ready),
      required: true,
      title: "A campaign with job titles and an ideal customer",
      detail: ready ? `"${ready.name}" is ready.` : "Without them people cannot be ranked and fit cannot be scored well.",
      action: <Link to="/campaigns" className="text-xs font-semibold text-primary hover:underline">Campaigns</Link>,
    },
    {
      ok: checked,
      title: "A mailbox connected and its DNS checked",
      detail: checked ? "SPF, DKIM and DMARC have been checked." : "Connect the mailbox drafts are saved in, then check its domain's SPF, DKIM and DMARC.",
      action: <button type="button" onClick={() => onOpen("mailboxes")} className="text-xs font-semibold text-primary hover:underline">Mailboxes</button>,
    },
    {
      ok: unreviewed.length === 0,
      title: "Country rules reviewed",
      detail: unreviewed.length ? `${unreviewed.length} countr${unreviewed.length === 1 ? "y allows" : "ies allow"} email without a named reviewer: ${unreviewed.map((x) => x.country_code).join(", ")}. A lawyer should check them.` : "Every country that allows email has a named reviewer.",
      action: <Link to="/compliance" className="text-xs font-semibold text-primary hover:underline">Policies</Link>,
    },
  ];
  const missing = items.filter((i) => !i.ok);
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card tour="setup-check" title="Setup check" subtitle={loading ? "Checking…" : missing.length === 0 ? "Everything is in place." : `${missing.length} of ${items.length} need attention.`}>
        <ul className="divide-y divide-line">
          {items.map((item) => (
            <li key={item.title} className="flex items-start gap-3 py-3">
              {loading ? (
                <Circle className="mt-0.5 size-4 shrink-0 text-outline" aria-hidden />
              ) : item.ok ? (
                <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-good" aria-label="Done" />
              ) : (
                <AlertTriangle className={`mt-0.5 size-4 shrink-0 ${item.required ? "text-error" : "text-attention"}`} aria-label={item.required ? "Missing" : "Warning"} />
              )}
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium">{item.title}</div>
                <div className="text-xs text-muted">{item.detail}</div>
              </div>
              {!item.ok && !loading && <div className="shrink-0">{item.action}</div>}
            </li>
          ))}
        </ul>
      </Card>
      <Card title="Elsewhere" className="h-fit">
        <ul className="space-y-2 text-[13px]">
          {[
            ["/campaigns", "Campaigns", "Job titles, ideal customer, questions"],
            ["/mailboxes", "Mailboxes", "Where drafts go; DNS check"],
            ["/compliance", "Policies and privacy", "Country rules, do not contact, erasure"],
          ].map(([to, title, detail]) => (
            <li key={to}>
              <Link to={to} className="group flex items-center justify-between rounded-lg border border-line px-3 py-2 hover:bg-surface-low">
                <span>
                  <span className="font-medium">{title}</span>
                  <span className="block text-[11px] text-muted">{detail}</span>
                </span>
                <ArrowRight className="size-4 text-muted transition-transform group-hover:translate-x-0.5" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ sender profile

const LEGAL: [string, string, string?][] = [
  ["legal_name", "Legal name", "Printed in every footer."],
  ["postal_address", "Postal address", "Required by the US, EU and Canadian footers."],
  ["registration_details", "Registration details", "Company number and where registered, for the UK footer."],
  ["contact_info", "Contact details", "A way to reach you, for the Canadian footer."],
];
const SIGNATURE: [string, string][] = [
  ["signature_name", "Your name"],
  ["signature_title", "Your title"],
];
const ABOUT: [string, string][] = [
  ["company_name", "Company name"],
  ["domain", "Website"],
  ["industry", "Industry"],
  ["geographic_focus", "Where you sell"],
];
const LISTS: [string, string, string][] = [
  ["value_propositions", "Value propositions", "What you offer, one per line."],
  ["case_studies", "Proof points", "One per line, and only what you can show. The writer may quote them."],
  ["technologies", "Technologies", "One per line."],
  ["target_verticals", "Target industries", "One per line."],
];

function SenderProfile() {
  const queryClient = useQueryClient();
  const profile = useQuery({ queryKey: ["sender"], queryFn: () => ok(client.GET("/api/settings/sender-profile")) });
  const policies = useQuery({ queryKey: ["policies"], queryFn: () => ok(client.GET("/api/settings/policies")) });
  const [draft, setDraft] = useState<Profile>({});
  // The one-per-line boxes keep exactly what was typed, so Enter makes a new line straight away.
  const [typed, setTyped] = useState<Record<string, string>>({});
  // Up to four emails the operator has sent: each is several paragraphs, so one box each.
  const [examples, setExamples] = useState<string[]>(["", "", "", ""]);
  useEffect(() => {
    const loaded = profile.data as Profile | undefined;
    if (!loaded) return;
    setDraft(loaded);
    const sent = (loaded.style_examples as string[] | undefined) ?? [];
    setExamples([0, 1, 2, 3].map((i) => sent[i] ?? ""));
    setTyped(Object.fromEntries(LISTS.map(([key]) => [key, ((loaded[key] as string[] | undefined) ?? []).join("\n")])));
  }, [profile.data]);
  const save = useMutation({
    mutationFn: () => {
      const listed = Object.fromEntries(LISTS.map(([key]) => [key, lines(typed[key] ?? "")]));
      const style_examples = examples.map((e) => e.trim()).filter(Boolean);
      return ok(client.PUT("/api/settings/sender-profile", { body: { ...draft, ...listed, style_examples } }));
    },
    onSuccess: () => {
      for (const key of ["sender", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  const text = (key: string) => String(draft[key] ?? "");
  const set = (key: string) => (e: { target: { value: string } }) => setDraft({ ...draft, [key]: e.target.value });

  return (
    <QueryState query={profile} rows={8}>
      {(saved) => {
        const reviewed = (saved as Profile).reviewed_at as string | undefined;
        return (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
            <div className="min-w-0 space-y-5">
              {reviewed ? (
                <Callout tone="good">Confirmed {when(reviewed)}. Saving again confirms it again.</Callout>
              ) : (
                <Callout tone="attention" title="Not confirmed yet">
                  Emails are not written until you have read this profile and saved it. Every statement here ends up in emails under your name, so keep only what is true and can be shown.
                </Callout>
              )}
              <Card title="1. Legal identity" subtitle="Printed in the footer the law of each country requires.">
                <div className="grid gap-3 sm:grid-cols-2">
                  {LEGAL.map(([key, label, hint]) => (
                    <Field key={key} label={label} hint={hint}>
                      {key === "postal_address" ? <Textarea rows={2} value={text(key)} onChange={set(key)} /> : <Input value={text(key)} onChange={set(key)} />}
                    </Field>
                  ))}
                </div>
              </Card>
              <Card title="2. Signature" subtitle="Ends every email.">
                <div className="grid gap-3 sm:grid-cols-2">
                  {SIGNATURE.map(([key, label]) => (
                    <Field key={key} label={label}>
                      <Input value={text(key)} onChange={set(key)} />
                    </Field>
                  ))}
                </div>
              </Card>
              <Card title="3. What the writer may use" subtitle="The copywriter draws on these. Only true statements.">
                <div className="grid gap-3 sm:grid-cols-2">
                  {ABOUT.map(([key, label]) => (
                    <Field key={key} label={label}>
                      <Input value={text(key)} onChange={set(key)} />
                    </Field>
                  ))}
                  <Field label="Mission" className="sm:col-span-2">
                    <Input value={text("mission")} onChange={set("mission")} />
                  </Field>
                  {LISTS.map(([key, label, hint]) => (
                    <Field key={key} label={label} hint={hint}>
                      <Textarea rows={4} value={typed[key] ?? ""} onChange={(e) => setTyped({ ...typed, [key]: e.target.value })} />
                    </Field>
                  ))}
                  <Field label="About you" hint="Background, voice and what sets you apart. The copywriter reads all of it." className="sm:col-span-2">
                    <Textarea rows={6} value={text("narrative")} onChange={set("narrative")} />
                  </Field>
                </div>
              </Card>
              <Card tour="settings-voice" title="4. How you write" subtitle="How the emails sound and what you want from them.">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Field label="Greeting" hint="Code adds it, so every email opens the same way.">
                    <Select value={text("greeting") || "Hi"} onChange={set("greeting")}>
                      <option value="Hi">Hi Jane,</option>
                      <option value="Hello">Hello Jane,</option>
                      <option value="Dear">Dear Jane,</option>
                    </Select>
                  </Field>
                  <Field label="What you want from these emails" hint="For example: explore a partnership, or book a demo. The closing ask follows it.">
                    <Textarea rows={2} value={text("outreach_goal")} onChange={set("outreach_goal")} placeholder="a short call to explore working together" />
                  </Field>
                </div>
                <Label className="mb-1 mt-4">Emails you have sent before (optional, up to four)</Label>
                <p className="mb-2 text-xs text-muted">
                  The writer reads these for what you offer and how direct you are. They are a reference, not a template: it will not copy their wording, greeting or bullet lists. Corrections you make on Review teach it more than these do.
                </p>
                <div className="grid gap-3 sm:grid-cols-2">
                  {examples.map((example, i) => (
                    <Textarea
                      key={i}
                      rows={6}
                      aria-label={`Past email ${i + 1}`}
                      value={example}
                      onChange={(e) => setExamples(examples.map((old, j) => (j === i ? e.target.value : old)))}
                      placeholder={`Past email ${i + 1}`}
                    />
                  ))}
                </div>
              </Card>
              <div className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface/95 px-4 py-3 backdrop-blur">
                <Button busy={save.isPending} onClick={() => save.mutate()}>
                  Confirm and save
                </Button>
                <SaveNote mutation={save} done="Saved and confirmed." />
              </div>
            </div>
            <FooterPreview profile={draft} policies={policies.data ?? []} />
          </div>
        );
      }}
    </QueryState>
  );
}

/** Field names a footer template may use, mapped to the profile key that fills them (domain/footer.py). */
const PLACEHOLDERS: Record<string, string> = {
  sender_legal_name: "legal_name",
  postal_address: "postal_address",
  registration_details: "registration_details",
  contact_info: "contact_info",
};

function FooterPreview({ profile, policies }: { profile: Profile; policies: { country_code: string; rule: string; footer_template?: string | null }[] }) {
  const withFooter = policies.filter((p) => p.footer_template);
  const [code, setCode] = useState("");
  const chosen = withFooter.find((p) => p.country_code === code) ?? withFooter.find((p) => p.country_code === "US") ?? withFooter[0];
  if (!chosen) return null;
  const parts = (chosen.footer_template ?? "").split(/(\{\w+\})/g);
  return (
    <Card title="Footer preview" className="h-fit xl:sticky xl:top-[72px]" subtitle="As this profile fills the country's footer. The server builds the real one.">
      <Segmented label="Country" value={chosen.country_code} onChange={setCode} options={withFooter.slice(0, 6).map((p) => [p.country_code, p.country_code] as const)} />
      <div className="mt-3 rounded-lg border border-line bg-surface-low p-3 text-xs leading-relaxed">
        <Label className="mb-1.5 flex items-center gap-1">
          <Lock className="size-3" aria-hidden /> Legal footer
        </Label>
        {parts.map((part, i) => {
          const name = part.match(/^\{(\w+)\}$/)?.[1];
          if (!name) return <span key={i}>{part}</span>;
          if (name === "data_source") return <span key={i}>your company&apos;s website</span>;
          const value = String(profile[PLACEHOLDERS[name] ?? name] ?? "").trim();
          return value ? (
            <span key={i} className="font-medium">
              {value}
            </span>
          ) : (
            <span key={i} className="rounded bg-error-container px-1 text-on-error-container">
              [missing {name.replaceAll("_", " ")}]
            </span>
          );
        })}
      </div>
      <p className="mt-2 text-[11px] text-muted">A missing field stops the email from being written for that country.</p>
    </Card>
  );
}

// ------------------------------------------------------------------ limits

function Limits() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const [safe, setSafe] = useState(true);
  const [budget, setBudget] = useState("0.50");
  const [examples, setExamples] = useState(5);
  const [footer, setFooter] = useState(true);
  const [minWords, setMinWords] = useState(120);
  const [maxWords, setMaxWords] = useState(200);
  useEffect(() => {
    const s = settings.data;
    if (!s) return;
    setSafe(Boolean(s.safe_to_send_only));
    // No stored ceiling means "no limit", which is a blank box, not zero.
    setBudget(s.budget_per_prospect_micro_usd == null ? "" : (Number(s.budget_per_prospect_micro_usd) / 1_000_000).toFixed(2));
    setExamples(Number(s.few_shot_examples ?? 5));
    setFooter(s.footer_enabled !== false);
    setMinWords(Number(s.email_min_words ?? 120));
    setMaxWords(Number(s.email_max_words ?? 200));
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () =>
      ok(
        client.PUT("/api/settings/workspace", {
          body: {
            safe_to_send_only: safe,
            budget_per_prospect_micro_usd: budget.trim() === "" ? null : Math.round(Number(budget) * 1_000_000),
            few_shot_examples: examples,
            footer_enabled: footer,
            email_min_words: minWords,
            email_max_words: maxWords,
          },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["workspace-settings"] }),
  });
  const badLength = minWords < 40 || maxWords > 600 || minWords > maxWords;
  const badBudget = budget.trim() !== "" && (Number.isNaN(Number(budget)) || Number(budget) < 0);
  return (
    <QueryState query={settings}>
      {() => (
        <Card title="Limits and budget" className="max-w-3xl">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Budget per prospect (USD)" hint="No paid call is made once a lead has spent this. Blank means no limit; 0 means no paid calls at all.">
              <Input type="number" step="0.01" min="0" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="no limit" />
            </Field>
            <Field label="Shortest first email (words)" hint="The writer is asked for this many at least; the check flags anything shorter. 40 to 600.">
              <Input type="number" min={40} max={600} value={minWords} onChange={(e) => setMinWords(Number(e.target.value))} />
            </Field>
            <Field label="Longest first email (words)" hint="Greeting, sign-off and footer are not counted. 120 to 200 reads like a real note.">
              <Input type="number" min={40} max={600} value={maxWords} onChange={(e) => setMaxWords(Number(e.target.value))} />
            </Field>
            <Field label="Earlier edits shown to the writer" hint="Your last N corrected emails in the campaign teach the writer your style (0 to 20).">
              <Input type="number" min={0} max={20} value={examples} onChange={(e) => setExamples(Number(e.target.value))} />
            </Field>
          </div>
          <div className="mt-4">
            <Checkbox checked={safe} onChange={setSafe} label="Only send to proven addresses (recommended)" hint="Catch-all addresses that could not be proven are held instead of drafted, because they bounce more often." />
          </div>
          <div className="mt-3" data-tour="settings-footer">
            <Checkbox
              checked={footer}
              onChange={setFooter}
              label="Add a footer to every email (recommended)"
              hint="Your company, postal address and a plain way to say no: the country's footer, or a short default where it has none. Kept when a country rule is skipped. The US, UK, EU and Canada expect an address and an opt-out even when no consent is needed."
            />
          </div>
          <p className="mt-4 text-xs text-muted">Automatic sending is off and cannot be switched on until the sending phase. Approved emails are saved as drafts.</p>
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3">
            <Button busy={save.isPending} disabled={badBudget || badLength} onClick={() => save.mutate()}>
              Save limits
            </Button>
            <SaveNote mutation={save} />
          </div>
        </Card>
      )}
    </QueryState>
  );
}
