import { Flame } from "lucide-react";
import { cx } from "../lib/cx";

/** The fit score as the engine sees it: above 80 a hot lead, with a flame; otherwise cold. */
export function FitBadge({ score, hot, className }: { score: number | null | undefined; hot: boolean; className?: string }) {
  if (score == null) return null;
  return (
    <span
      title={hot ? "Hot lead: a fit score above 80. Its email always waits for you in Review." : "Cold lead: a fit score of 80 or lower."}
      className={cx(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 font-mono text-caption font-semibold",
        hot ? "bg-attention-container text-on-attention-container" : "bg-surface-container text-muted",
        className,
      )}
    >
      {hot && <Flame className="size-3" aria-label="Hot" />}
      {score}
      {!hot && <span className="sr-only"> (cold)</span>}
    </span>
  );
}
