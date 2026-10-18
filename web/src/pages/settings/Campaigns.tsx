import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../../api/client";
import { Button, Card, Field, Input, Problem, Textarea } from "../../components/ui";
import { lines } from "./shared";

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

export function Campaigns() {
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
