import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { client, ok } from "../../api/client";
import { Button, Card, Field, Input, QueryState, SaveNote, Textarea, when } from "../../components/ui";
import { lines, useSave } from "./shared";

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
  ["case_studies", "Proof points (one per line, only what you can show)"],
  ["target_verticals", "Target verticals (one per line)"],
];

export function SenderProfile() {
  const profile = useQuery({ queryKey: ["sender"], queryFn: () => ok(client.GET("/api/settings/sender-profile")) });
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  // The one-per-line boxes keep exactly what was typed. Splitting into lines on every keystroke
  // would drop the empty line a new Enter makes, so Enter would seem to do nothing.
  const [typed, setTyped] = useState<Record<string, string>>({});
  useEffect(() => {
    const loaded = profile.data as Record<string, unknown> | undefined;
    if (!loaded) return;
    setDraft(loaded);
    setTyped(Object.fromEntries(LISTS.map(([key]) => [key, ((loaded[key] as string[] | undefined) ?? []).join("\n")])));
  }, [profile.data]);
  const save = useSave("sender", () => {
    const listed = Object.fromEntries(LISTS.map(([key]) => [key, lines(typed[key] ?? "")]));
    return ok(client.PUT("/api/settings/sender-profile", { body: { ...draft, ...listed } }));
  });
  const text = (key: string) => String(draft[key] ?? "");
  return (
    <QueryState query={profile}>
      {(saved) => {
        const reviewed = (saved as Record<string, unknown>).reviewed_at as string | undefined;
        return (
    <Card tour="sender-profile" title="Sender profile" actions={<Button onClick={() => save.mutate(undefined)}>Confirm and save</Button>}>
      {reviewed ? (
        <p className="mb-3 text-xs text-muted">Last confirmed {when(reviewed)}.</p>
      ) : (
        <p role="alert" className="mb-3 rounded-md border border-amber-300 bg-amber-50 p-2 text-sm">
          <strong>Not confirmed yet.</strong> Emails are not written until you have read this profile and saved it. Every statement here ends up in emails under your name, so keep only what is true and can be shown.
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {SCALARS.map(([key, label, hint]) => (
          <Field key={key} label={label} hint={hint}>
            <Input value={text(key)} onChange={(e) => setDraft({ ...draft, [key]: e.target.value })} />
          </Field>
        ))}
        {LISTS.map(([key, label]) => (
          <Field key={key} label={label}>
            <Textarea rows={4} value={typed[key] ?? ""} onChange={(e) => setTyped({ ...typed, [key]: e.target.value })} />
          </Field>
        ))}
        <div className="sm:col-span-2">
          <Field label="About you (the copywriter reads this)">
            <Textarea rows={8} value={text("narrative")} onChange={(e) => setDraft({ ...draft, narrative: e.target.value })} />
          </Field>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <SaveNote mutation={save} done="Saved and confirmed." />
      </div>
    </Card>
        );
      }}
    </QueryState>
  );
}
