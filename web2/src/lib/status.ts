/**
 * Every status the server reports, as a label and one of five families (design brief, Section 7).
 * Values come from outbound/domain/enums.py. An unknown value still renders: it gets a readable
 * label and the neutral family, so a new status on the server never breaks a screen.
 */

export type Family = "working" | "attention" | "good" | "stopped" | "error";

export type StatusInfo = { label: string; family: Family };

type Vocabulary = Record<string, StatusInfo>;

const s = (label: string, family: Family): StatusInfo => ({ label, family });

export const leadStatus: Vocabulary = {
  new: s("New", "working"),
  researched: s("Researched", "working"),
  qualified: s("Qualified", "working"),
  contacts_found: s("Contacts found", "working"),
  email_ready: s("Email ready", "working"),
  copy_ready: s("Copy ready", "attention"),
  held: s("Held", "attention"),
  approved: s("Approved", "good"),
  in_sequence: s("In sequence", "good"),
  replied: s("Replied", "good"),
  completed: s("Completed", "good"),
  disqualified: s("Disqualified", "stopped"),
  rejected: s("Rejected", "stopped"),
  suppressed: s("Suppressed", "stopped"),
  failed: s("Failed", "error"),
};

export const emailStatus: Vocabulary = {
  valid: s("Valid", "good"),
  catch_all_resolved: s("Catch-all resolved", "good"),
  unverified: s("Unverified", "stopped"),
  catch_all_pending: s("Catch-all pending", "working"),
  catch_all_unverified: s("Catch-all unverified", "attention"),
  unknown: s("Unknown", "stopped"),
  invalid: s("Invalid", "error"),
};

/** Proven safe (PLAN.md §7), or the operator chose to skip the check for this address. */
export const isSafeToSend = (status: string, verificationSkipped = false): boolean =>
  verificationSkipped || status === "valid" || status === "catch_all_resolved";

export const messageState: Vocabulary = {
  generated: s("Waiting for review", "attention"),
  approved: s("Approved", "good"),
  rejected: s("Rejected", "stopped"),
  drafted: s("Drafted", "good"),
  sent: s("Sent", "good"),
  bounced: s("Bounced", "error"),
  cancelled: s("Cancelled", "stopped"),
};

export const runStatus: Vocabulary = {
  queued: s("Queued", "working"),
  running: s("Running", "working"),
  succeeded: s("Succeeded", "good"),
  failed: s("Failed", "error"),
  cancelled: s("Cancelled", "stopped"),
};

export const importRowStatus: Vocabulary = {
  pending: s("Pending", "working"),
  needs_confirmation: s("Needs confirmation", "attention"),
  accepted: s("Accepted", "good"),
  merged: s("Merged", "good"),
  rejected: s("Rejected", "stopped"),
};

export const callOutcome: Vocabulary = {
  hit: s("Hit", "good"),
  miss: s("Miss", "stopped"),
  error: s("Error", "error"),
  cache_hit: s("Cache hit, free", "good"),
  blocked_by_cap: s("Blocked by cap", "attention"),
};

/**
 * A hold, in plain words: what it means and what fixes it (USER_MANUAL.md §7.1). ``action`` says
 * which control resolves it: set the country, add a person with consent, wait for the resolver,
 * or open the lead and decide.
 */
export type HoldAction = "country" | "person" | "wait" | "decide";
export type HoldInfo = { label: string; why: string; fix: string; action: HoldAction };

export const holdReason: Record<string, HoldInfo> = {
  country_unknown: {
    label: "Country unknown",
    why: "The country could not be worked out, and the rules depend on it.",
    fix: "Set the country, then release the hold.",
    action: "country",
  },
  entity_unknown: {
    label: "Company type unknown",
    why: "UK rules allow cold email only to incorporated companies, and nothing proved this one is.",
    fix: "Add a Companies House key so it can be checked, or add a person who has consented.",
    action: "person",
  },
  consent_required: {
    label: "Consent required",
    why: "The country or company type needs the person's consent before any email.",
    fix: "Add the person who agreed to be contacted, with where their consent came from.",
    action: "person",
  },
  catch_all_resolving: {
    label: "Catch-all resolving",
    why: "The address is on a server that accepts anything; a resolver is checking it (1–3 days).",
    fix: "Nothing to do. The lead is released when the resolver answers.",
    action: "wait",
  },
  catch_all_unverified: {
    label: "Catch-all unverified",
    why: "The resolver could not prove the address, and an unproven address risks a bounce.",
    fix: "Usually leave it held.",
    action: "decide",
  },
  needs_operator: {
    label: "Needs you",
    why: "The rules for this country are missing or incomplete.",
    fix: "Add or review the country's policy in Settings, then choose where to resume.",
    action: "decide",
  },
};

const humanize = (value: string): string => {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

/** Look a value up in a vocabulary, falling back to a readable, neutral badge. */
export function describe(vocabulary: Vocabulary, value: string): StatusInfo {
  return vocabulary[value] ?? { label: humanize(value), family: "stopped" };
}

export function describeHold(reason: string): HoldInfo {
  return holdReason[reason] ?? { label: humanize(reason), why: "", fix: "", action: "decide" };
}

/** The eight stages a lead passes through, as the journey page names them. */
export const STAGES = ["Intake", "Research", "Qualification", "People", "Email address", "Copy", "Review", "Draft and outreach"] as const;

/**
 * How many stages a status has finished, for the compact stage bar in lists. Statuses that leave
 * the main path (held, failed, disqualified...) report no position: the list shows their badge,
 * and the journey page has the exact stage.
 */
const STAGES_DONE: Record<string, number> = {
  new: 1,
  researched: 2,
  qualified: 3,
  contacts_found: 4,
  email_ready: 5,
  copy_ready: 6,
  approved: 7,
  in_sequence: 8,
  replied: 8,
  completed: 8,
};

export const stagesDone = (status: string): number | null => STAGES_DONE[status] ?? null;

/** Every lead status, in pipeline order, for filters. */
export const LEAD_STATUSES = Object.keys(leadStatus);
export const HOLD_REASONS = Object.keys(holdReason);
