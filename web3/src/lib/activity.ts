import type { Schemas } from "../api/client";
import { words } from "./format";
import { describe, describeHold, leadStatus } from "./status";

export type TimelineEvent = Schemas["TimelineOut"];
type Tone = "good" | "attention" | "error" | "plain";

export type Line = { text: string; tone: Tone; minor: boolean };

const str = (value: unknown): string => (typeof value === "string" ? value : value == null ? "" : String(value));

/** What a lead's status change means, in the words an operator uses. */
function moved(to: string, data: Record<string, unknown>, fit: number | null): Line {
  switch (to) {
    case "researched":
      return { text: "Research finished", tone: "plain", minor: false };
    case "qualified":
      return { text: fit != null ? `Passed the fit check (${fit}/100)` : "Passed the fit check", tone: "good", minor: false };
    case "disqualified":
      return { text: str(data.reason) ? `Stopped at the fit check: ${str(data.reason)}` : "Stopped at the fit check", tone: "attention", minor: false };
    case "contacts_found":
      return { text: "People found", tone: "plain", minor: false };
    case "email_ready":
      return { text: "Address found", tone: "good", minor: false };
    case "copy_ready":
      return { text: "Draft written", tone: "good", minor: false };
    case "approved":
      return { text: "Email approved", tone: "good", minor: false };
    case "in_sequence":
      return { text: "Draft saved to the mailbox", tone: "good", minor: false };
    case "held":
      return { text: `Put on hold: ${describeHold(str(data.hold_reason)).label}`, tone: "attention", minor: false };
    case "failed":
      return { text: `A step failed${str(data.error) ? `: ${str(data.error)}` : ""}`, tone: "error", minor: false };
    case "new":
      return { text: str(data.reason) ? `Sent back to the start (${str(data.reason)})` : "Sent back to the start", tone: "plain", minor: false };
    default:
      return { text: `Moved to ${describe(leadStatus, to).label.toLowerCase()}`, tone: "plain", minor: false };
  }
}

/**
 * One event as one plain sentence, or null when it is not worth showing (the engine's attempts
 * to overwrite a value the operator set are in "Your values kept"). `names` maps contact ids to
 * people; `fit` is the lead's score.
 */
export function describeEvent(event: TimelineEvent, names: Record<string, string>, fit: number | null): Line | null {
  const d = event.data as Record<string, unknown>;
  const who = names[event.entity_id];
  switch (event.type) {
    case "created":
      if (event.entity_type === "company") return { text: str(d.source) ? `Lead added (${words(str(d.source))})` : "Lead added", tone: "plain", minor: false };
      if (event.entity_type === "contact") return { text: who ? `${who} found` : "A person was found", tone: "plain", minor: false };
      if (event.entity_type === "message") return { text: "An email was written", tone: "good", minor: false };
      return { text: "An address was recorded", tone: "plain", minor: true };
    case "status_changed": {
      const to = str(d.to);
      if (event.entity_type === "message") {
        const map: Record<string, Line> = {
          approved: { text: "Email approved", tone: "good", minor: false },
          rejected: { text: `Email rejected${str(d.reason) ? `: ${str(d.reason)}` : ""}`, tone: "attention", minor: false },
          drafted: { text: "Draft saved to the mailbox", tone: "good", minor: false },
          sent: { text: "Email sent", tone: "good", minor: false },
          bounced: { text: "Email bounced", tone: "error", minor: false },
          cancelled: { text: "Email cancelled", tone: "plain", minor: false },
        };
        return map[to] ?? { text: `Email ${words(to)}`, tone: "plain", minor: true };
      }
      if (event.entity_type === "contact") return { text: `${who ?? "A person"}: ${words(to)}`, tone: "plain", minor: true };
      if (event.entity_type === "contact_email") return { text: `An address was checked: ${words(to)}`, tone: "plain", minor: true };
      return moved(to, d, fit);
    }
    case "edited":
      return { text: `Email edited${typeof d.edit_distance === "number" ? ` (${Math.round(d.edit_distance * 100)}% changed)` : ""}`, tone: "plain", minor: false };
    case "approved_with_skips":
      return { text: "Approved while relying on a check you skipped", tone: "attention", minor: false };
    case "consent_recorded":
      return { text: `Consent recorded${who ? ` for ${who}` : ""}`, tone: "good", minor: false };
    case "consent_withdrawn":
      return { text: "Consent withdrawn", tone: "attention", minor: false };
    case "person_removed":
      return { text: "A person was removed", tone: "plain", minor: false };
    case "deferred":
      return { text: `Waiting: ${str(d.reason) || "a step will try again"}`, tone: "plain", minor: true };
    case "resumed":
      return { text: "Resumed after waiting for credits", tone: "plain", minor: false };
    case "revision_asked":
      return { text: "A rewrite was asked for", tone: "plain", minor: true };
    case "policy_skip_granted":
      return { text: "The country rule was skipped for this lead", tone: "attention", minor: false };
    case "policy_skip_revoked":
      return { text: "The country rule applies again", tone: "plain", minor: false };
    case "skip_directory":
      return { text: "Emails come from the vendors, not the shared directory", tone: "plain", minor: true };
    case "field_changed":
      if (d.applied === false) return null; // shown under "Your values kept"
      return { text: `${words(str(d.field))} changed`, tone: "plain", minor: true };
    default:
      return { text: words(event.type), tone: "plain", minor: true };
  }
}

export type Day = { label: string; lines: { at: string; line: Line; count: number; by: string | null }[] };

const dayKey = (iso: string) => new Date(iso).toDateString();

function dayLabel(iso: string): string {
  const then = new Date(iso);
  const today = new Date();
  const yesterday = new Date(today.getTime() - 86_400_000);
  if (then.toDateString() === today.toDateString()) return "Today";
  if (then.toDateString() === yesterday.toDateString()) return "Yesterday";
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

/**
 * The events as days, newest first. Identical lines that follow each other (a step waiting again
 * and again) become one with a count. `detailed` includes the minor events.
 */
export function activityDays(events: TimelineEvent[], names: Record<string, string>, fit: number | null, detailed: boolean): Day[] {
  const days: Day[] = [];
  for (const event of [...events].reverse()) {
    const line = describeEvent(event, names, fit);
    if (!line || (line.minor && !detailed)) continue;
    const key = dayKey(event.at);
    let day = days.at(-1);
    if (!day || dayKey(day.lines[0]!.at) !== key) {
      day = { label: dayLabel(event.at), lines: [] };
      days.push(day);
    }
    const last = day.lines.at(-1);
    if (last && last.line.text === line.text) {
      last.count += 1;
      continue;
    }
    day.lines.push({ at: event.at, line, count: 1, by: event.actor === "operator" ? "you" : null });
  }
  return days;
}
