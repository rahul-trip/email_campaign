/** AI-credit and run charts shared by Reports and Runs (from web2's dashboard). */
import { cx } from "../lib/cx";
import { credits } from "../lib/format";

export function BudgetMeter({ spent, ceiling }: { spent: number; ceiling: number }) {
  const used = Math.min(100, Math.round((spent / ceiling) * 100));
  return (
    <div className="col-span-2">
      <div className="mb-1 flex justify-between tnum text-label text-muted">
        <span>Average per lead against the budget</span>
        <span className={cx("font-semibold", used > 90 ? "text-error" : used > 70 ? "text-attention" : "text-good")}>{used}% used</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-surface-3" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={used} aria-label="Budget used">
        <div className={cx("h-full rounded-full", used > 90 ? "bg-error" : used > 70 ? "bg-attention" : "bg-primary")} style={{ width: `${Math.max(2, used)}%` }} />
      </div>
    </div>
  );
}

export function ProviderBars({ byProvider, calls, total }: { byProvider: Record<string, number>; calls: Record<string, number>; total: number }) {
  const rows = Object.keys({ ...calls, ...byProvider }).sort((a, b) => (byProvider[b] ?? 0) - (byProvider[a] ?? 0) || (calls[b] ?? 0) - (calls[a] ?? 0));
  if (rows.length === 0) return <p className="text-small text-muted">No vendor calls recorded yet.</p>;
  return (
    <ul className="space-y-2">
      {rows.map((vendor) => {
        const micro = byProvider[vendor] ?? 0;
        const share = total > 0 ? Math.round((micro / total) * 100) : 0;
        return (
          <li key={vendor}>
            <div className="flex items-center justify-between gap-2 tnum text-small">
              <span className="font-medium">{vendor}</span>
              <span className="text-muted">
                {calls[vendor] ?? 0} calls · {credits(micro)} {total > 0 && `(${share}%)`}
              </span>
            </div>
            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-3">
              <div className="h-full bg-primary" style={{ width: `${share}%` }} />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** A run's counts, per stage: "research 6 advanced · gate 5 advanced, 1 held". */
export function RunCounts({ counts }: { counts: Record<string, unknown> | null | undefined }) {
  const stages = Object.entries(counts ?? {}).filter(([, value]) => typeof value === "object" && value && Object.keys(value).length > 0) as [string, Record<string, number>][];
  if (stages.length === 0) return <p className="text-small text-muted">No lead moved in this run.</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {stages.map(([stage, outcome]) => (
        <li key={stage} className="rounded-md border border-line bg-surface-2 px-2 py-0.5 text-label">
          <span className="font-semibold">{stage}</span>{" "}
          <span className="text-muted">
            {Object.entries(outcome)
              .map(([kind, n]) => `${n} ${kind}`)
              .join(", ")}
          </span>
        </li>
      ))}
    </ul>
  );
}


/** Until every required step is done, the dashboard leads with what is left. */
