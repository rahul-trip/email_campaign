import { useQuery } from "@tanstack/react-query";
import { client, ok, type Schemas } from "../api/client";

export type Usage = Schemas["UsageOut"];

/** The plan and what is left on it. Read again every minute and after every save. */
export const useUsage = () => useQuery({ queryKey: ["usage"], queryFn: () => ok(client.GET("/api/usage")), refetchInterval: 60_000 });

export const STEP_LABEL: Record<string, string> = {
  discovery: "Leads found by search",
  manual: "Leads you add",
  research: "Research",
  email: "Finding emails",
  copy: "Writing",
  deliver: "Drafts saved to the mailbox",
  rewrite: "Rewrites and changes",
};

/** Steps whose meter is worth showing: limited, or already used. */
export const shown = (usage: Usage) => usage.steps.filter((s) => s.limit !== null || s.used > 0 || s.granted > 0);

export const waitingTotal = (usage?: Usage) => (usage ? Object.values(usage.waiting_leads).reduce((a, b) => a + b, 0) + usage.waiting_rows : 0);

export const day = (iso?: string | null) => (iso ? new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "");

/** Steps at or over this share of their limit get a warning banner. */
export const NEAR = 0.8;
export function nearLimit(usage: Usage) {
  return usage.steps.filter((s) => s.limit !== null && s.limit > 0 && (s.used >= s.limit || s.used / s.limit >= NEAR)).map((s) => ({ ...s, out: (s.remaining ?? 1) <= 0 }));
}
