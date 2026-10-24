import type { ReactNode } from "react";
import type { Schemas } from "../api/client";
import { cx } from "../lib/cx";
import { STEP_LABEL } from "../lib/usage";

export type Row = Schemas["CustomerRowOut"];

/** A local date, with the exact UTC time on hover. */
export function When({ iso, time }: { iso?: string | null; time?: boolean }) {
  if (!iso) return <span className="text-muted">—</span>;
  const d = new Date(iso);
  return (
    <time dateTime={iso} title={`${d.toISOString().replace("T", " ").slice(0, 16)} UTC`}>
      {time ? d.toLocaleString() : d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
    </time>
  );
}

export function Pill({ tone, children }: { tone: "good" | "attention" | "error" | "muted"; children: ReactNode }) {
  const tones = { good: "bg-good-container text-on-good-container", attention: "bg-attention-container text-on-attention-container", error: "bg-error-container text-on-error-container", muted: "bg-surface-container text-muted" };
  return <span className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold", tones[tone])}>{children}</span>;
}

export function AccessPill({ row }: { row: Pick<Row, "access" | "access_until" | "status"> }) {
  if (row.status === "suspended") return <Pill tone="error">Suspended</Pill>;
  if (row.status === "paused") return <Pill tone="attention">Engine paused</Pill>;
  if (row.access === "read_only") return <Pill tone="error">Ended {row.access_until ? new Date(row.access_until).toLocaleDateString() : ""}</Pill>;
  if (!row.access_until) return <Pill tone="good">No end</Pill>;
  const days = Math.ceil((new Date(row.access_until).getTime() - Date.now()) / 86_400_000);
  return <Pill tone={days <= 7 ? "attention" : "good"}>Until {new Date(row.access_until).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</Pill>;
}

/** used / total with a small bar. No total: just the number used. */
export function UseBar({ used, total, label }: { used: number; total: number | null; label?: string }) {
  if (total === null) return <span className="font-mono text-xs">{label ? `${label} ` : ""}{used}</span>;
  const share = total === 0 ? 1 : Math.min(1, used / total);
  return (
    <span className="inline-flex items-center gap-1.5 font-mono text-xs">
      {label && <span className="w-7 text-muted">{label}</span>}
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-surface-container">
        <span className={cx("block h-full rounded-full", share >= 1 ? "bg-error" : share >= 0.8 ? "bg-attention" : "bg-primary-container")} style={{ width: `${share * 100}%` }} />
      </span>
      {used}/{total}
    </span>
  );
}

export const stepName = (step: string) => STEP_LABEL[step] ?? step;

export const StepOf = (row: Row, step: string) => row.steps.find((s) => s.step === step);
