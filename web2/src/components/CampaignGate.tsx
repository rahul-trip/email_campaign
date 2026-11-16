import { Callout, Card, PageHeader } from "./ui";
import { useIsAdmin } from "../app/session";
import { FirstCampaign } from "../pages/Campaigns";

/**
 * Shown in place of every page until the workspace has an active campaign that says who it
 * reaches: job titles and an ideal customer. Research, ranking, fit and discovery all read it.
 */
export function CampaignGate() {
  const admin = useIsAdmin();
  return (
    <div data-tour="campaign-gate">
      <PageHeader title="Create your campaign" subtitle="One short form before anything else: who you want to reach. The engine cannot find, rank or score anyone without it." />
      {admin ? (
        <Card title="Your campaign" subtitle="Name it, list the job titles you want to reach and describe your ideal customer. You can change all of it later under Campaigns.">
          <FirstCampaign />
        </Card>
      ) : (
        <Callout tone="attention" title="An admin has to set this up">
          This workspace has no campaign yet. Ask one of its admins to create it; the app opens as soon as they have.
        </Callout>
      )}
    </div>
  );
}
