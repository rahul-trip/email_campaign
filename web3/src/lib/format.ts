/**
 * AI credits arrive as integer thousandths (milli-credits), so a small model call is not rounded
 * to a whole credit. Large amounts read as whole credits; small ones keep a decimal or two.
 */
export function credits(milli: number | null | undefined, unit = true): string {
  const value = (milli ?? 0) / 1000;
  const size = Math.abs(value);
  const digits = value === 0 || size >= 10 ? 0 : size >= 1 ? 1 : 2;
  const text = value.toLocaleString(undefined, { maximumFractionDigits: digits });
  return unit ? `${text} ${size === 1 ? "credit" : "credits"}` : text;
}

/**
 * What calls cost the platform, from integer micro-USD. For the admin console only: customers see
 * AI credits, never dollars. Small amounts keep more places.
 */
export function usd(micro: number | null | undefined): string {
  const value = (micro ?? 0) / 1_000_000;
  return `$${value.toFixed(value !== 0 && Math.abs(value) < 0.1 ? 4 : 2)}`;
}

/** Whole AI credits (plans, grants, caps), or "No limit". */
export const wholeCredits = (n: number | null | undefined): string => (n == null ? "No limit" : `${n.toLocaleString()} ${n === 1 ? "credit" : "credits"}`);

export const percent = (share: number | null | undefined): string =>
  share === null || share === undefined ? "–" : `${Math.round(share * 100)}%`;

/** A local date and time, for tables and tooltips. */
export const when = (iso?: string | null): string => (iso ? new Date(iso).toLocaleString() : "");

/** "3 min ago", for live lists. Falls back to the date after a week. */
export function ago(iso?: string | null, now: number = Date.now()): string {
  if (!iso) return "";
  const seconds = Math.round((now - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} d ago`;
  return new Date(iso).toLocaleDateString();
}

/** A duration between two times, such as "1 min 20 s". */
export function duration(start?: string | null, end?: string | null, now: number = Date.now()): string {
  if (!start) return "";
  const seconds = Math.max(0, Math.round(((end ? new Date(end).getTime() : now) - new Date(start).getTime()) / 1000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  return minutes < 60 ? `${minutes} min ${seconds % 60} s` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

/** An enum value as words: "contacts_found" becomes "contacts found". */
export const words = (text: string): string => text.replaceAll("_", " ");

/** Text typed one item per line, as a list without blank lines. */
export const lines = (text: string): string[] =>
  text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);

/** A stored failure message as a person should read it: a stage's own words, without the program's class name that older rows carry. */
export const plainError = (text: string | null | undefined): string => (text ?? "").replace(/^StageFailure:\s*/, "");
