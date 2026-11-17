/**
 * Money is integer micro-USD on the server (1 USD = 1,000,000). Totals read best with cents; a
 * single vendor call often costs a fraction of a cent, so small amounts keep more places.
 */
export function usd(micro: number | null | undefined, places?: number): string {
  const value = (micro ?? 0) / 1_000_000;
  const digits = places ?? (value !== 0 && Math.abs(value) < 0.1 ? 4 : 2);
  return `$${value.toFixed(digits)}`;
}

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
