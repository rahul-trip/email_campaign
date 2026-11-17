/** The sender profile's fields, shared by Settings (all of them) and onboarding (a few at a time).
 * One definition of each field: a new one is added here and shows up in both. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { client, ok } from "../api/client";
import { Card, Field, Input, Label, Segmented, Select, Textarea } from "../ui/compat";
import { lines } from "../lib/format";

export type Profile = Record<string, unknown>;

export const LEGAL: [string, string, string?][] = [
  ["legal_name", "Legal name", "Printed in every footer."],
  ["postal_address", "Postal address", "Required by the US, EU and Canadian footers."],
  ["registration_details", "Registration details", "Company number and where registered, for the UK footer."],
  ["contact_info", "Contact details", "A way to reach you, for the Canadian footer."],
];
export const SIGNATURE: [string, string][] = [
  ["signature_name", "Your name"],
  ["signature_title", "Your title"],
];
export const ABOUT: [string, string][] = [
  ["company_name", "Company name"],
  ["domain", "Website"],
  ["industry", "Industry"],
  ["geographic_focus", "Where you sell"],
];
export const LISTS: [string, string, string][] = [
  ["value_propositions", "Value propositions", "What you offer, one per line."],
  ["case_studies", "Proof points", "One per line, and only what you can show. The writer may quote them."],
  ["technologies", "Technologies", "One per line."],
  ["target_verticals", "Target industries", "One per line."],
];
const LIST_KEYS = new Set(LISTS.map(([key]) => key));

/** Field names a footer template may use, mapped to the profile key that fills them (domain/footer.py). */
const PLACEHOLDERS: Record<string, string> = {
  sender_legal_name: "legal_name",
  postal_address: "postal_address",
  registration_details: "registration_details",
  contact_info: "contact_info",
};

/** Load, edit, fill from a suggestion and save the profile. Saving confirms it (the server sets `reviewed_at`). */
export function useSenderProfile() {
  const queryClient = useQueryClient();
  const query = useQuery({ queryKey: ["sender"], queryFn: () => ok(client.GET("/api/settings/sender-profile")) });
  const [draft, setDraft] = useState<Profile>({});
  // The one-per-line boxes keep exactly what was typed, so Enter makes a new line straight away.
  const [typed, setTyped] = useState<Record<string, string>>({});
  // Up to four emails the operator has sent: each is several paragraphs, so one box each.
  const [examples, setExamples] = useState<string[]>(["", "", "", ""]);
  // The keys a suggestion filled, so the screen can say "check this".
  const [filled, setFilled] = useState<Set<string>>(new Set());
  useEffect(() => {
    const loaded = query.data as Profile | undefined;
    if (!loaded) return;
    setDraft(loaded);
    const sent = (loaded.style_examples as string[] | undefined) ?? [];
    setExamples([0, 1, 2, 3].map((i) => sent[i] ?? ""));
    setTyped(Object.fromEntries(LISTS.map(([key]) => [key, ((loaded[key] as string[] | undefined) ?? []).join("\n")])));
  }, [query.data]);

  const save = useMutation({
    mutationFn: () => {
      const listed = Object.fromEntries(LISTS.map(([key]) => [key, lines(typed[key] ?? "")]));
      const style_examples = examples.map((e) => e.trim()).filter(Boolean);
      return ok(client.PUT("/api/settings/sender-profile", { body: { ...draft, ...listed, style_examples } }));
    },
    onSuccess: () => {
      for (const key of ["sender", "status", "setup"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  const text = (key: string) => String(draft[key] ?? "");
  const set = (key: string) => (e: { target: { value: string } }) => setDraft((old) => ({ ...old, [key]: e.target.value }));

  /** Put a suggestion into the form. Only blank fields change: what the person typed stays. */
  const fill = (suggested: Record<string, unknown>) => {
    const done = new Set<string>();
    const nextDraft: Profile = {};
    const nextTyped: Record<string, string> = {};
    for (const [key, value] of Object.entries(suggested)) {
      if (LIST_KEYS.has(key)) {
        if (!(typed[key] ?? "").trim() && Array.isArray(value) && value.length) {
          nextTyped[key] = value.map(String).join("\n");
          done.add(key);
        }
      } else if (!String(draft[key] ?? "").trim() && typeof value === "string" && value.trim()) {
        nextDraft[key] = value;
        done.add(key);
      }
    }
    setDraft((old) => ({ ...old, ...nextDraft }));
    setTyped((old) => ({ ...old, ...nextTyped }));
    setFilled(done);
  };

  return { query, draft, setDraft, text, set, typed, setTyped, examples, setExamples, filled, fill, save };
}
export type SenderProfileState = ReturnType<typeof useSenderProfile>;

export function LegalFields({ p }: { p: SenderProfileState }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {LEGAL.map(([key, label, hint]) => (
        <Field key={key} label={label} hint={hint}>
          {key === "postal_address" ? <Textarea rows={2} value={p.text(key)} onChange={p.set(key)} /> : <Input value={p.text(key)} onChange={p.set(key)} />}
        </Field>
      ))}
    </div>
  );
}

export function SignatureFields({ p }: { p: SenderProfileState }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {SIGNATURE.map(([key, label]) => (
        <Field key={key} label={label}>
          <Input value={p.text(key)} onChange={p.set(key)} />
        </Field>
      ))}
    </div>
  );
}

const FROM_SITE = "From your website. Check it.";
const mark = (p: SenderProfileState, key: string, hint?: string) => (p.filled.has(key) ? (hint ? `${FROM_SITE} ${hint}` : FROM_SITE) : hint);

/** What the writer may use. `only` shows a subset of the fields, by key. */
export function AboutFields({ p, only }: { p: SenderProfileState; only?: string[] }) {
  const show = (key: string) => !only || only.includes(key);
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {ABOUT.filter(([key]) => show(key)).map(([key, label]) => (
        <Field key={key} label={label} hint={mark(p, key)}>
          <Input value={p.text(key)} onChange={p.set(key)} />
        </Field>
      ))}
      {show("mission") && (
        <Field label="Mission" hint={mark(p, "mission")} className="sm:col-span-2">
          <Input value={p.text("mission")} onChange={p.set("mission")} />
        </Field>
      )}
      {LISTS.filter(([key]) => show(key)).map(([key, label, hint]) => (
        <Field key={key} label={label} hint={mark(p, key, hint)}>
          <Textarea rows={4} value={p.typed[key] ?? ""} onChange={(e) => p.setTyped({ ...p.typed, [key]: e.target.value })} />
        </Field>
      ))}
      {show("narrative") && (
        <Field label="About you" hint={mark(p, "narrative", "Background, voice and what sets you apart. The copywriter reads all of it.")} className="sm:col-span-2">
          <Textarea rows={6} value={p.text("narrative")} onChange={p.set("narrative")} />
        </Field>
      )}
    </div>
  );
}

/** How the emails sound and what you want from them. */
export function VoiceFields({ p }: { p: SenderProfileState }) {
  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Greeting" hint="Code adds it, so every email opens the same way.">
          <Select value={p.text("greeting") || "Hi"} onChange={p.set("greeting")}>
            <option value="Hi">Hi Jane,</option>
            <option value="Hello">Hello Jane,</option>
            <option value="Dear">Dear Jane,</option>
          </Select>
        </Field>
        <OutreachGoal p={p} />
      </div>
      <Label className="mb-1 mt-4">Emails you have sent before (optional, up to four)</Label>
      <p className="mb-2 text-small text-muted">
        The writer reads these for what you offer and how direct you are. They are a reference, not a template: it will not copy their wording, greeting or bullet lists. Corrections you make on Review teach it more than these do.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {p.examples.map((example, i) => (
          <Textarea
            key={i}
            rows={6}
            aria-label={`Past email ${i + 1}`}
            value={example}
            onChange={(e) => p.setExamples(p.examples.map((old, j) => (j === i ? e.target.value : old)))}
            placeholder={`Past email ${i + 1}`}
          />
        ))}
      </div>
    </>
  );
}

export function OutreachGoal({ p }: { p: SenderProfileState }) {
  return (
    <Field label="What you want from these emails" hint="For example: explore a partnership, or book a demo. The closing ask follows it.">
      <Textarea rows={2} value={p.text("outreach_goal")} onChange={p.set("outreach_goal")} placeholder="a short call to explore working together" />
    </Field>
  );
}

/** The country footer as this profile fills it. Loads the country rules itself. */
export function FooterPreview({ profile }: { profile: Profile }) {
  const policies = useQuery({ queryKey: ["policies"], queryFn: () => ok(client.GET("/api/settings/policies")) });
  const withFooter = (policies.data ?? []).filter((p) => p.footer_template);
  const [code, setCode] = useState("");
  const chosen = withFooter.find((p) => p.country_code === code) ?? withFooter.find((p) => p.country_code === "US") ?? withFooter[0];
  if (!chosen) return null;
  const parts = (chosen.footer_template ?? "").split(/(\{\w+\})/g);
  return (
    <Card title="Footer preview" className="h-fit xl:sticky xl:top-[72px]" subtitle="As this profile fills the country's footer. The server builds the real one.">
      <Segmented label="Country" value={chosen.country_code} onChange={setCode} options={withFooter.slice(0, 6).map((p) => [p.country_code, p.country_code] as const)} />
      <div className="mt-3 rounded-lg border border-line bg-surface-2 p-3 text-small leading-relaxed">
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
            <span key={i} className="rounded bg-error-soft px-1 text-error">
              [missing {name.replaceAll("_", " ")}]
            </span>
          );
        })}
      </div>
      <p className="mt-2 text-label text-muted">A missing field stops the email from being written for that country.</p>
    </Card>
  );
}
