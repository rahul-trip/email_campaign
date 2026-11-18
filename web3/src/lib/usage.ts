import { useQuery } from "@tanstack/react-query";
import { client, ok, type Schemas } from "../api/client";

export type Usage = Schemas["UsageOut"];

/** The plan and what is left on it. Read again every minute and after every save. */
export const useUsage = () => useQuery({ queryKey: ["usage"], queryFn: () => ok(client.GET("/api/usage")), refetchInterval: 60_000 });

/** Where a lead waits when AI credits run out: the step it waits at. */
export const STEP_LABEL: Record<string, string> = {
  discovery: "Leads found by search",
  manual: "Leads you add",
  research: "Research",
  email: "Finding emails",
  copy: "Writing",
  deliver: "Drafts saved to the mailbox",
  rewrite: "Rewrites and changes",
};

export const waitingTotal = (usage?: Usage) => (usage ? Object.values(usage.waiting_leads).reduce((a, b) => a + b, 0) + usage.waiting_rows : 0);

export const day = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");

/** At or over this share of the AI credits used, a warning banner shows. */
export const NEAR = 0.8;

/** How far through its AI credits a workspace is: null when it has no limit. */
export function creditState(usage: Usage): { used: number; allowance: number; share: number; out: boolean } | null {
  const { allowance, used_milli, remaining_milli } = usage.credits;
  if (allowance == null) return null;
  const used = used_milli / 1000;
  const share = allowance > 0 ? used / allowance : 1;
  return { used, allowance, share, out: (remaining_milli ?? 1) <= 0 };
}

export const nearLimit = (usage: Usage) => {
  const state = creditState(usage);
  return state !== null && (state.out || state.share >= NEAR) ? state : null;
};
