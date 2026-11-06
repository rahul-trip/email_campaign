import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Megaphone, Plus, Sparkles } from "lucide-react";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Card, Empty, Field, Input, PageHeader, QueryState, SaveNote, Segmented, Textarea } from "../components/ui";
import { lines } from "../lib/format";

type Campaign = Schemas["CampaignOut"];

export function CampaignsPage() {
  const queryClient = useQueryClient();
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  const [adding, setAdding] = useState(false);
  const saved = () => void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
  return (
    <>
      <PageHeader
        title="Campaigns"
        subtitle="Who you want to reach and what makes a good customer. Research, ranking and the fit score all read this."
        actions={
          !adding && (
            <Button onClick={() => setAdding(true)}>
              <Plus className="size-4" aria-hidden /> New campaign
            </Button>
          )
        }
      />
      <div className="space-y-5">
        {adding && (
          <Card title="New campaign">
            <CampaignForm
              onSaved={() => {
                setAdding(false);
                saved();
              }}
              onCancel={() => setAdding(false)}
            />
          </Card>
        )}
        <QueryState query={campaigns}>
          {(all) =>
            all.length === 0 && !adding ? (
              <Card>
                <Empty icon={<Megaphone className="size-8" />} title="No campaign yet" action={<Button onClick={() => setAdding(true)}>Create a campaign</Button>}>
                  A campaign lists the job titles you want, describes your ideal customer and sets the minimum fit score.
                </Empty>
              </Card>
            ) : (
              <>
                {all.map((c, i) => (
                  <div key={c.id} className="space-y-5">
                    <Card title={c.name} subtitle={`Minimum fit ${c.min_fit_score} · ${c.target_titles.length} job title${c.target_titles.length === 1 ? "" : "s"}`}>
                      <CampaignForm campaign={c} onSaved={saved} />
                    </Card>
                    <BriefCard key={JSON.stringify(c.icp_brief)} campaign={c} onSaved={saved} tour={i === 0 ? "campaign-brief" : undefined} />
                  </div>
                ))}
              </>
            )
          }
        </QueryState>
      </div>
    </>
  );
}

export function CampaignForm({ campaign, onSaved, onCancel }: { campaign?: Campaign; onSaved: () => void; onCancel?: () => void }) {
  const [name, setName] = useState(campaign?.name ?? "");
  const [titles, setTitles] = useState((campaign?.target_titles ?? []).join("\n"));
  const [icp, setIcp] = useState(campaign?.icp_description ?? "");
  const [minFit, setMinFit] = useState(campaign?.min_fit_score ?? 60);
  const [questions, setQuestions] = useState((campaign?.research_questions ?? []).join("\n"));
  const [cadence, setCadence] = useState((campaign?.cadence_days ?? [0, 3, 8]).join(", "));
  const tooMany = lines(questions).length > 3;
  const save = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(),
        target_titles: lines(titles),
        icp_description: icp.trim() || null,
        min_fit_score: minFit,
        research_questions: lines(questions),
        cadence_days: cadence
          .split(",")
          .map((n) => n.trim())
          .filter(Boolean)
          .map(Number)
          .filter((n) => Number.isInteger(n) && n >= 0),
      };
      return campaign
        ? ok(client.PATCH("/api/settings/campaigns/{campaign_id}", { params: { path: { campaign_id: campaign.id } }, body }))
        : ok(client.POST("/api/settings/campaigns", { body }));
    },
    onSuccess: onSaved,
  });
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Field label="Name">
        <Input value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      <Field label={`Minimum fit score: ${minFit}`} hint="Discovered companies below this are disqualified. Companies you add by hand skip this check.">
        <div className="flex items-center gap-3">
          <input type="range" min={0} max={100} value={minFit} onChange={(e) => setMinFit(Number(e.target.value))} className="h-8 flex-1 accent-[var(--primary-container)]" aria-label="Minimum fit score" />
          <Input type="number" min={0} max={100} value={minFit} onChange={(e) => setMinFit(Number(e.target.value))} className="w-20" aria-label="Minimum fit score, as a number" />
        </div>
      </Field>
      <Field label="Wanted job titles" hint="One per line, best first. People found are ranked against these.">
        <Textarea rows={4} value={titles} onChange={(e) => setTitles(e.target.value)} placeholder={"Head of Trading\nCOO"} />
      </Field>
      <Field label="Research questions" hint={tooMany ? "At most 3 questions." : "Up to 3, one per line. The research answers each one for every company."}>
        <Textarea rows={4} value={questions} onChange={(e) => setQuestions(e.target.value)} />
      </Field>
      <Field label="Ideal customer" hint="Plain words: who they are, their size, what they do. The fit score and discovery read this." className="md:col-span-2">
        <Textarea rows={3} value={icp} onChange={(e) => setIcp(e.target.value)} />
      </Field>
      <Field label="Follow-up days" hint="Business days after the first email, comma separated. Stored now; follow-ups arrive in a later phase.">
        <Input value={cadence} onChange={(e) => setCadence(e.target.value)} className="font-mono" />
      </Field>
      <div className="flex flex-wrap items-end gap-3">
        <Button busy={save.isPending} disabled={!name.trim() || tooMany} onClick={() => save.mutate()}>
          {campaign ? "Save campaign" : "Create campaign"}
        </Button>
        {onCancel && (
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <SaveNote mutation={save} done={campaign ? "Campaign saved." : "Campaign created."} />
      </div>
    </div>
  );
}

/** Mirrors outbound/domain/brief.py; the API sends it as plain JSON. */
type Criterion = { text: string; weight?: number };
type Brief = Record<string, unknown> & { summary?: string; company_type?: string; size_range?: string; founded_after?: number | null; must_haves?: Criterion[] };

const COMPANY_TYPES = [
  ["any", "Any"],
  ["startup", "Start-ups"],
  ["sme", "Small and mid-sized"],
  ["enterprise", "Enterprises"],
  ["public_sector", "Public sector"],
] as const;
type CompanyType = (typeof COMPANY_TYPES)[number][0];

/** The one-per-line lists of the brief, with what each is for. */
const BRIEF_LISTS: [string, string, string][] = [
  ["keywords", "What they do", "Market, product and technology words that describe these companies. Searches are built from them."],
  ["segments", "Kinds of company", "For example B2B SaaS start-ups, or regional utilities."],
  ["regions", "Where", "Countries or regions."],
  ["disqualifiers", "Rule out", "Anything here drops a company, for example a competitor that sells what you sell."],
  ["buying_signals", "Signs they may buy now", "For example recent funding, hiring, a new project."],
  ["source_hints", "Where such companies are listed", "Kinds of page that name many of them: accelerator cohorts, funding round-ups, association members, award lists."],
  ["funding_stages", "Funding stages", "Only for start-ups, for example seed or series A."],
  ["industry_codes", "UK SIC codes", "Five-digit codes such companies register under, for the Companies House search."],
  ["seed_companies", "Example customers", "Websites of companies just like the ones you want. Used to find lookalikes."],
];

/** "Text (3)" means weight 3; no number means 1. */
const criteriaText = (items: Criterion[] | undefined) => (items ?? []).map((c) => (c.weight && c.weight > 1 ? `${c.text} (${c.weight})` : c.text)).join("\n");
const criteriaFrom = (text: string) =>
  lines(text).map((line) => {
    const m = /^(.*?)\s*\(([1-3])\)$/.exec(line);
    return m ? { text: m[1], weight: Number(m[2]) } : { text: line, weight: 1 };
  });

function BriefCard({ campaign, onSaved, tour }: { campaign: Campaign; onSaved: () => void; tour?: string }) {
  const brief = (campaign.icp_brief ?? {}) as Brief;
  const list = (key: string) => ((brief[key] as string[] | undefined) ?? []).join("\n");
  const [summary, setSummary] = useState(String(brief.summary ?? ""));
  const [kind, setKind] = useState<CompanyType>((brief.company_type as CompanyType | undefined) ?? "any");
  const [size, setSize] = useState(String(brief.size_range ?? ""));
  const [founded, setFounded] = useState(brief.founded_after ? String(brief.founded_after) : "");
  const [mustHaves, setMustHaves] = useState(criteriaText(brief.must_haves));
  const [typed, setTyped] = useState<Record<string, string>>(Object.fromEntries(BRIEF_LISTS.map(([key]) => [key, list(key)])));
  const path = { params: { path: { campaign_id: campaign.id } } };
  const save = useMutation({
    mutationFn: () => {
      const icp_brief = {
        summary: summary.trim(),
        company_type: kind,
        size_range: size.trim(),
        founded_after: Number.parseInt(founded, 10) || null,
        must_haves: criteriaFrom(mustHaves),
        ...Object.fromEntries(BRIEF_LISTS.map(([key]) => [key, lines(typed[key] ?? "")])),
      };
      return ok(client.PATCH("/api/settings/campaigns/{campaign_id}", { ...path, body: { icp_brief } }));
    },
    onSuccess: onSaved,
  });
  const draft = useMutation({
    mutationFn: () => ok(client.POST("/api/settings/campaigns/{campaign_id}/brief/regenerate", path)),
    onSuccess: onSaved,
  });
  const empty = !campaign.icp_brief;
  return (
    <Card
      tour={tour}
      title="Who we look for"
      subtitle="Discovery searches from this, drops companies that do not fit it, and research checks each lead against it."
      actions={
        <Button variant="secondary" busy={draft.isPending} onClick={() => draft.mutate()}>
          <Sparkles className="size-4" aria-hidden /> {empty ? "Draft from the campaign" : "Draft again"}
        </Button>
      }
    >
      {empty ? (
        <p className="text-sm text-muted">
          Not drafted yet. Draft it from the ideal customer above and your sender profile, then check it; the first discovery run drafts it if you have not.
        </p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          <Field label="In short" className="md:col-span-2">
            <Textarea rows={3} value={summary} onChange={(e) => setSummary(e.target.value)} />
          </Field>
          <Field label="Kind of company" hint="Start-ups also search start-up directories such as Y Combinator." className="md:col-span-2">
            <Segmented label="Kind of company" value={kind} options={COMPANY_TYPES} onChange={setKind} />
          </Field>
          <Field label="Must have" hint="One per line. Add (3) after one that is essential, (2) after one that matters; no number means it only helps." className="md:col-span-2">
            <Textarea rows={4} value={mustHaves} onChange={(e) => setMustHaves(e.target.value)} />
          </Field>
          {BRIEF_LISTS.map(([key, label, hint]) => (
            <Field key={key} label={label} hint={hint}>
              <Textarea rows={3} value={typed[key] ?? ""} onChange={(e) => setTyped({ ...typed, [key]: e.target.value })} />
            </Field>
          ))}
          <Field label="Size">
            <Input value={size} onChange={(e) => setSize(e.target.value)} placeholder="10-200 employees" />
          </Field>
          <Field label="Founded after">
            <Input type="number" value={founded} onChange={(e) => setFounded(e.target.value)} className="w-28" />
          </Field>
          <div className="flex flex-wrap items-end gap-3 md:col-span-2">
            <Button busy={save.isPending} onClick={() => save.mutate()}>
              Save brief
            </Button>
            <SaveNote mutation={save} done="Brief saved." />
          </div>
        </div>
      )}
      <SaveNote mutation={draft} done="Brief drafted. Check it, then save any change." />
    </Card>
  );
}
