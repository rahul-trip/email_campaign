import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Megaphone, Plus } from "lucide-react";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Card, Empty, Field, Input, PageHeader, QueryState, SaveNote, Textarea } from "../components/ui";
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
                {all.map((c) => (
                  <Card key={c.id} title={c.name} subtitle={`Minimum fit ${c.min_fit_score} · ${c.target_titles.length} job title${c.target_titles.length === 1 ? "" : "s"}`}>
                    <CampaignForm campaign={c} onSaved={saved} />
                  </Card>
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
