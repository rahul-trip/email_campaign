/** What a run's stored counts mean, in one place for the list and the detail page. */

export type Counts = Record<string, Record<string, number>>;

/** The steps a run goes through, in order (a run that is still going has finished only the first few). */
export const STAGES = ["research", "gate", "contacts", "email", "copy", "deliver"] as const;

export const STAGE_LABEL: Record<string, string> = {
  research: "Research",
  gate: "Fit check",
  contacts: "Find people",
  email: "Find emails",
  copy: "Write emails",
  deliver: "Save drafts",
  discovery: "Discovery",
};

export const OUTCOME_LABEL: Record<string, string> = {
  advanced: "moved on",
  held: "held",
  failed: "failed",
  suppressed: "suppressed",
  deferred: "will retry",
  waiting: "waiting for credits",
  skipped: "skipped",
};

export function countsOf(raw: unknown): Counts {
  const out: Counts = {};
  for (const [stage, value] of Object.entries((raw ?? {}) as Record<string, unknown>)) {
    if (value && typeof value === "object") out[stage] = value as Record<string, number>;
  }
  return out;
}

export interface Totals {
  moved: number;
  held: number;
  failed: number;
  retry: number;
  waiting: number;
  newLeads: number;
  alreadyLeads: number;
  searches: number;
  hasDiscovery: boolean;
}

/** Leads are counted once per step they went through, so "moved" is steps completed, not distinct leads. */
export function totalsOf(raw: unknown): Totals {
  const counts = countsOf(raw);
  const t: Totals = { moved: 0, held: 0, failed: 0, retry: 0, waiting: 0, newLeads: 0, alreadyLeads: 0, searches: 0, hasDiscovery: false };
  for (const [stage, outcomes] of Object.entries(counts)) {
    if (stage === "discovery") {
      t.hasDiscovery = true;
      t.newLeads = outcomes["new leads"] ?? 0;
      t.alreadyLeads = outcomes["already leads"] ?? 0;
      t.searches = outcomes.searches ?? 0;
      continue;
    }
    t.moved += outcomes.advanced ?? 0;
    t.held += outcomes.held ?? 0;
    t.failed += outcomes.failed ?? 0;
    t.retry += outcomes.deferred ?? 0;
    t.waiting += outcomes.waiting ?? 0;
  }
  return t;
}

/** How many of the steps have reported, for a run that is still going. */
export function stagesDone(raw: unknown): number {
  const counts = countsOf(raw);
  return STAGES.filter((s) => s in counts).length;
}

/** A sentence for the discovery part of a run, or null when it did no discovery. */
export function discoveryLine(t: Totals): string | null {
  if (!t.hasDiscovery) return null;
  const tried = t.searches ? ` in ${t.searches} search${t.searches === 1 ? "" : "es"}` : "";
  if (t.newLeads === 0 && t.alreadyLeads > 0) return `Discovery found only companies you already have${tried}. The next run takes new angles.`;
  if (t.newLeads === 0) return `Discovery found no new companies${tried}.`;
  return `Discovery added ${t.newLeads} new lead${t.newLeads === 1 ? "" : "s"}${tried}${t.alreadyLeads ? `, skipping ${t.alreadyLeads} you already have` : ""}.`;
}
