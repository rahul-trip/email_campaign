import type { Family, StatusInfo } from "../lib/status";
import { cx } from "../lib/cx";

const families: Record<Family, string> = {
  working: "bg-working-soft text-working",
  attention: "bg-attention-soft text-attention",
  good: "bg-good-soft text-good",
  stopped: "bg-stopped-soft text-stopped",
  error: "bg-error-soft text-error",
};

const dots: Record<Family, string> = {
  working: "bg-working",
  attention: "bg-attention",
  good: "bg-good",
  stopped: "bg-stopped",
  error: "bg-error",
};

/** A status as a pill: a dot and a word, never colour alone. */
export function StatusBadge({ status, title }: { status: StatusInfo; title?: string }) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-small font-medium",
        families[status.family],
      )}
    >
      <span aria-hidden className={cx("size-1.5 rounded-full", dots[status.family])} />
      {status.label}
    </span>
  );
}
