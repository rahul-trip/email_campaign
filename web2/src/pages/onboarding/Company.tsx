/** Step 1: read the company's own website, check what was drafted, confirm. */
import { useMutation } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { client, ok } from "../../api/client";
import { Button, Callout, Card, Field, Input, Problem, QueryState } from "../../components/ui";
import { when } from "../../lib/format";
import { AboutFields, useSenderProfile, type Profile } from "../SenderProfileParts";

const MAIN = ["company_name", "domain", "industry", "geographic_focus", "value_propositions", "case_studies", "narrative"];
const MORE = ["mission", "technologies", "target_verticals"];

const WHY: Record<string, string> = {
  site_unreadable: "We could not read that website. Check the address, or fill the form in yourself.",
  bad_website: "We could not read that website. Check the address, or fill the form in yourself.",
  no_model: "A draft could not be written just now. Fill the form in yourself; it takes a few minutes.",
  no_search: "A draft could not be written just now. Fill the form in yourself; it takes a few minutes.",
  model_failed: "A draft could not be written just now. Fill the form in yourself; it takes a few minutes.",
  daily_limit: "Your website has been read five times today. Fill the rest in yourself, or try again tomorrow.",
};

export function Company({ onNext }: { onNext: () => void }) {
  const p = useSenderProfile();
  const [typedSite, setTypedSite] = useState<string | null>(null);
  const [hidden, setHidden] = useState(false);
  const website = typedSite ?? p.text("domain");
  const read = useMutation({
    mutationFn: () => ok(client.POST("/api/setup/profile-draft", { body: { website: website.trim() } })),
    onSuccess: (found) => {
      if (found.drafted) p.fill(found.fields);
    },
  });
  return (
    <QueryState query={p.query} rows={6}>
      {(saved) => {
        const reviewed = (saved as Profile).reviewed_at as string | undefined;
        const found = read.data;
        return (
          <div className="space-y-4">
            {(!reviewed && !hidden) || read.isPending || found ? (
              <div className="rounded-lg border border-line bg-surface-low p-3">
                <div className="flex flex-wrap items-end gap-3">
                  <Field label="Your website" className="min-w-[220px] flex-1">
                    <Input value={website} onChange={(e) => setTypedSite(e.target.value)} placeholder="example.com" />
                  </Field>
                  <Button busy={read.isPending} disabled={!website.trim()} onClick={() => read.mutate()}>
                    <Sparkles className="size-4" aria-hidden /> Read my website
                  </Button>
                  {!reviewed && !found && (
                    <button type="button" className="pb-2 text-xs font-semibold text-primary hover:underline" onClick={() => setHidden(true)}>
                      Fill it in myself
                    </button>
                  )}
                </div>
                {read.isPending && <p className="mt-2 text-xs text-muted">Reading your website and drafting your profile. This takes about half a minute.</p>}
                <Problem error={read.error} className="mt-2" />
              </div>
            ) : null}
            {found?.drafted && (
              <>
                <Callout tone="good">
                  Drafted from {found.pages.length} page{found.pages.length === 1 ? "" : "s"} of your website. Check each line and change what is wrong. Nothing is saved until you confirm.
                </Callout>
                <Card collapsible title="Pages we read">
                  <ul className="list-disc pl-4 text-xs">
                    {found.pages.map((url) => (
                      <li key={url}>
                        <a href={url} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                          {url}
                        </a>
                      </li>
                    ))}
                  </ul>
                </Card>
              </>
            )}
            {found && !found.drafted && <Callout tone="attention">{WHY[found.reason ?? "model_failed"]}</Callout>}
            {reviewed && <Callout tone="good">Confirmed {when(reviewed)}. Saving again confirms it again.</Callout>}
            <AboutFields p={p} only={MAIN} />
            <Card collapsible forceOpen={MORE.some((k) => p.filled.has(k))} title="Add more detail (optional)">
              <AboutFields p={p} only={MORE} />
            </Card>
            <div className="flex flex-wrap items-center gap-3">
              <Button busy={p.save.isPending} onClick={() => p.save.mutate(undefined, { onSuccess: onNext })}>
                Confirm and continue
              </Button>
              <span className="text-xs text-muted">By confirming you say these statements are true.</span>
            </div>
            <Problem error={p.save.error} />
          </div>
        );
      }}
    </QueryState>
  );
}
