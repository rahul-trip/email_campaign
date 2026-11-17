/** Small visual anchors: progress rings, sparklines, numbers that count up, delta badges. */
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { cx } from "../lib/cx";

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** A number that counts up to its value the first time it appears. */
export function CountUp({ value, format = (n) => Math.round(n).toLocaleString(), duration = 700 }: { value: number; format?: (n: number) => string; duration?: number }) {
  const [shown, setShown] = useState(reduced() ? value : 0);
  const from = useRef(0);
  useEffect(() => {
    if (reduced()) {
      setShown(value);
      return;
    }
    const start = performance.now();
    const begin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      const eased = 1 - (1 - t) ** 3;
      setShown(begin + (value - begin) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
      else from.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return <span className="tnum">{format(shown)}</span>;
}

/** A progress ring. ``share`` is 0 to 1; the label sits in the middle. */
export function Ring({ share, size = 64, stroke = 7, tone = "primary", label, title }: { share: number; size?: number; stroke?: number; tone?: "primary" | "good" | "attention" | "error"; label?: React.ReactNode; title?: string }) {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(1, share));
  const color = { primary: "var(--primary)", good: "var(--good-dot)", attention: "var(--attention-dot)", error: "var(--error-dot)" }[tone];
  return (
    <div className="relative inline-flex shrink-0 items-center justify-center" style={{ width: size, height: size }} role="img" aria-label={title ?? `${Math.round(clamped * 100)}%`}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--surface-3)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={c * (1 - clamped)}
          style={{ transition: "stroke-dashoffset 0.9s cubic-bezier(0.2,0.9,0.3,1)" }}
        />
      </svg>
      {label !== undefined && <span className="tnum absolute text-small font-bold text-ink">{label}</span>}
    </div>
  );
}

/** A tiny line of the last days. Flat and quiet when everything is zero. */
export function Sparkline({ values, className, tone = "primary", height = 32, width = 96 }: { values: number[]; className?: string; tone?: "primary" | "good" | "attention"; height?: number; width?: number }) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const step = width / (values.length - 1);
  const points = values.map((v, i) => [i * step, height - 3 - (v / max) * (height - 6)] as const);
  const line = points.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const color = { primary: "var(--primary)", good: "var(--good-dot)", attention: "var(--attention-dot)" }[tone];
  const id = `spark-${tone}`;
  return (
    <svg width={width} height={height} className={cx("overflow-visible", className)} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.22" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${line} L${width},${height} L0,${height} Z`} fill={`url(#${id})`} />
      <path d={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={points[points.length - 1]![0]} cy={points[points.length - 1]![1]} r="2.5" fill={color} />
    </svg>
  );
}

/** "+6 vs last week": up is good unless ``invert``. Nothing to compare shows a dash. */
export function Delta({ now, before, unit = "", invert, label = "vs last week" }: { now: number; before: number; unit?: string; invert?: boolean; label?: string }) {
  const diff = now - before;
  const good = invert ? diff < 0 : diff > 0;
  const Icon = diff === 0 ? Minus : diff > 0 ? ArrowUpRight : ArrowDownRight;
  return (
    <span className="inline-flex items-center gap-1.5 text-small text-muted">
      <span className={cx("tnum inline-flex items-center gap-0.5 rounded-md px-1.5 py-0.5 font-semibold", diff === 0 ? "bg-surface-3 text-muted" : good ? "bg-good-soft text-good" : "bg-error-soft text-error")}>
        <Icon className="size-3.5" aria-hidden />
        {diff > 0 ? "+" : ""}
        {Number.isInteger(diff) ? diff : diff.toFixed(1)}
        {unit}
      </span>
      {label}
    </span>
  );
}

/** A fit score as a small ring with hot / warm / cold colour and the number inside. */
export function FitRing({ score, size = 36 }: { score: number | null | undefined; size?: number }) {
  if (score === null || score === undefined) return <span className="text-small text-faint">—</span>;
  const tone = score > 80 ? "good" : score >= 60 ? "primary" : "attention";
  return <Ring share={score / 100} size={size} stroke={4} tone={tone} label={score} title={`Fit ${score} of 100`} />;
}
