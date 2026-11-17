/** Step 3: who to reach. The campaign is suggested from the profile; the brief discovery works from is drafted and shown. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { client, ok } from "../../api/client";
import { Button, Card, Problem } from "../../ui/compat";
import { BriefSummary, FirstCampaign } from "../Campaigns";

export function Audience({ onNext }: { onNext: () => void }) {
  const queryClient = useQueryClient();
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  const active = campaigns.data?.find((c) => c.status === "active");
  const ready = Boolean(active && active.target_titles.length > 0 && active.icp_description);
  const drafted = useRef(false);
  const draft = useMutation({
    mutationFn: (id: string) => ok(client.POST("/api/settings/campaigns/{campaign_id}/brief/regenerate", { params: { path: { campaign_id: id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["campaigns"] }),
  });
  // Once the campaign says who it is for, draft the brief discovery will search from.
  useEffect(() => {
    if (active && ready && !active.icp_brief && !drafted.current) {
      drafted.current = true;
      draft.mutate(active.id);
    }
  }, [active, ready, draft]);
  return (
    <div className="space-y-4">
      <FirstCampaign autoSuggest />
      {ready && (
        <Card title="This is who we will look for" subtitle="Written from your campaign and profile. Discovery searches from it, and every lead is checked against it.">
          {draft.isPending && <p className="text-sm text-muted">Drafting this from your campaign…</p>}
          <Problem error={draft.error} />
          {active?.icp_brief ? <BriefSummary campaign={active} /> : !draft.isPending && <p className="text-sm text-muted">It could not be drafted just now. You can write it under Campaigns.</p>}
        </Card>
      )}
      {ready && (
        <Button onClick={onNext} disabled={draft.isPending}>
          Looks right, find my first leads
        </Button>
      )}
    </div>
  );
}
