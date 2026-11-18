/**
 * web3's building blocks. Every colour comes from the tokens in styles.css, so each piece works
 * in light and dark. Motion is CSS only and switches off with "reduce motion".
 */
import type { UseQueryResult } from "@tanstack/react-query";
import { AlertCircle, Loader2 } from "lucide-react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { ApiProblem } from "../api/client";
import { cx } from "../lib/cx";
import type { Family } from "../lib/status";

// ------------------------------------------------------------------ buttons

type Variant = "primary" | "secondary" | "ghost" | "danger" | "soft";
type Size = "sm" | "md" | "lg";

const VARIANT: Record<Variant, string> = {
  primary: "bg-primary text-primary-ink hover:bg-primary-hover",
  secondary: "border border-line-strong bg-surface text-ink hover:bg-surface-2",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
  danger: "border border-error/20 bg-error-soft text-error hover:border-error/40",
  soft: "bg-primary-soft text-primary hover:bg-primary/15",
};
const SIZE: Record<Size, string> = {
  sm: "h-8 gap-1.5 rounded-lg px-3 text-small",
  md: "h-10 gap-2 rounded-[var(--radius-control)] px-4 text-body",
  lg: "h-12 gap-2 rounded-xl px-6 text-[1rem]",
};

export const buttonClass = (variant: Variant = "primary", size: Size = "md", className?: string) =>
  cx(
    "press inline-flex shrink-0 items-center justify-center font-semibold whitespace-nowrap disabled:pointer-events-none disabled:opacity-50",
    VARIANT[variant],
    SIZE[size],
    className,
  );

export function Button({
  variant = "primary",
  size = "md",
  busy,
  className,
  children,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; busy?: boolean }) {
  return (
    <button type={type} className={buttonClass(variant, size, className)} disabled={busy || props.disabled} aria-busy={busy || undefined} {...props}>
      {busy && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ status

const FAMILY: Record<Family, { chip: string; dot: string }> = {
  working: { chip: "bg-working-soft text-working", dot: "bg-working-dot" },
  attention: { chip: "bg-attention-soft text-attention", dot: "bg-attention-dot" },
  good: { chip: "bg-good-soft text-good", dot: "bg-good-dot" },
  stopped: { chip: "bg-stopped-soft text-stopped", dot: "bg-stopped-dot" },
  error: { chip: "bg-error-soft text-error", dot: "bg-error-dot" },
};
export type Tone = Family | "primary" | "neutral";

/** A pill with a word in it. Colour is never the only signal: there is always text. */
export function Chip({ tone = "neutral", children, dot, pulse, className, title }: { tone?: Tone; children: ReactNode; dot?: boolean; pulse?: boolean; className?: string; title?: string }) {
  const style =
    tone === "primary" ? { chip: "bg-primary-soft text-primary", dot: "bg-primary" } : tone === "neutral" ? { chip: "bg-surface-3 text-ink-2", dot: "bg-faint" } : FAMILY[tone];
  return (
    <span title={title} className={cx("inline-flex h-6 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-label font-semibold whitespace-nowrap", style.chip, className)}>
      {dot && <span aria-hidden className={cx("size-1.5 rounded-full", style.dot, pulse && "animate-pulse-dot text-current")} />}
      {children}
    </span>
  );
}

export function Dot({ tone, pulse }: { tone: Family; pulse?: boolean }) {
  return <span aria-hidden className={cx("inline-block size-2 rounded-full", FAMILY[tone].dot, pulse && "animate-pulse-dot text-current")} />;
}

// ------------------------------------------------------------------ text and layout

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-label font-semibold tracking-wide text-muted uppercase">{eyebrow}</div>}
        <h1 className="text-[1.75rem] leading-9 font-semibold tracking-tight text-ink">{title}</h1>
        {subtitle && <p className="mt-1.5 max-w-[65ch] text-body text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ children, className, hover, as: As = "div", ...rest }: { children: ReactNode; className?: string; hover?: boolean; as?: "div" | "section" | "article" } & Record<string, unknown>) {
  return (
    <As className={cx("card", hover && "card-hover", className)} {...rest}>
      {children}
    </As>
  );
}

export const Label = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={cx("text-label font-semibold tracking-wide text-faint uppercase", className)}>{children}</div>
);

export const Mono = ({ children, className }: { children: ReactNode; className?: string }) => <span className={cx("font-mono text-[0.8125rem]", className)}>{children}</span>;

export function Callout({ tone = "primary", title, children, icon, className, action }: { tone?: Tone; title?: ReactNode; children?: ReactNode; icon?: ReactNode; className?: string; action?: ReactNode }) {
  const bg = tone === "primary" ? "bg-primary-soft border-primary-line" : tone === "neutral" ? "bg-surface-2 border-line" : `${FAMILY[tone].chip.split(" ")[0]} border-line`;
  return (
    <div role={tone === "error" ? "alert" : undefined} className={cx("flex gap-3 rounded-xl border px-4 py-3", bg, className)}>
      {icon && <div className="mt-0.5 shrink-0">{icon}</div>}
      <div className="min-w-0 flex-1 text-body text-ink-2">
        {title && <div className="font-semibold text-ink">{title}</div>}
        {children}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ loading, empty, errors

export type SkeletonShape = "lines" | "cards" | "table" | "stat";

/** Placeholders shaped like what will arrive, so the page does not jump when it loads. */
export function Skeleton({ rows = 3, className, shape = "lines" }: { rows?: number; className?: string; shape?: SkeletonShape }) {
  const bar = "shimmer rounded-md";
  return (
    <div role="status" aria-label="Loading" className={cx(shape === "lines" && "space-y-3", className)}>
      {shape === "cards" && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: Math.max(rows, 3) }, (_, i) => (
            <div key={i} className="rounded-2xl border border-line p-5">
              <div className={cx(bar, "h-3 w-1/3")} />
              <div className={cx(bar, "mt-4 h-7 w-1/2")} />
              <div className={cx(bar, "mt-4 h-3 w-5/6")} />
            </div>
          ))}
        </div>
      )}
      {shape === "stat" && (
        <>
          <div className={cx(bar, "h-3 w-2/5")} />
          <div className={cx(bar, "mt-3 h-8 w-1/3")} />
        </>
      )}
      {shape === "table" && (
        <div className="divide-y divide-line">
          {Array.from({ length: rows }, (_, i) => (
            <div key={i} className="flex items-center gap-4 py-3">
              <div className={cx(bar, "size-9 shrink-0 rounded-xl")} />
              <div className="min-w-0 flex-1 space-y-2">
                <div className={cx(bar, "h-3.5")} style={{ width: `${55 - ((i * 13) % 25)}%` }} />
                <div className={cx(bar, "h-3 w-1/4")} />
              </div>
              <div className={cx(bar, "hidden h-6 w-20 rounded-full sm:block")} />
            </div>
          ))}
        </div>
      )}
      {shape === "lines" &&
        Array.from({ length: rows }, (_, i) => <div key={i} className={cx(bar, "h-4")} style={{ width: `${92 - ((i * 17) % 35)}%` }} />)}
    </div>
  );
}

export function Problem({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className={cx("flex gap-2 rounded-xl border border-error/25 bg-error-soft px-3 py-2.5 text-small text-error", className)}>
      <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div>
        {message}
        {error instanceof ApiProblem && error.status === 409 && <span className="mt-0.5 block font-medium">This changed since you opened it. Reload and try again.</span>}
        {error instanceof ApiProblem && error.fields.length > 0 && (
          <ul className="mt-1 list-disc pl-4">
            {error.fields.map((f) => (
              <li key={f.field + f.message}>
                {f.field}: {f.message}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function QueryState<T>({ query, children, rows, shape }: { query: UseQueryResult<T>; children: (data: T) => ReactNode; rows?: number; shape?: SkeletonShape }) {
  if (query.isPending) return <Skeleton rows={rows} shape={shape} />;
  if (query.isError) return <Problem error={query.error} />;
  return <>{children(query.data as T)}</>;
}

export function Empty({ art, title, children, action, className }: { art?: ReactNode; title: ReactNode; children?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-col items-center px-6 py-10 text-center", className)}>
      {art && <div className="mb-4 animate-pop">{art}</div>}
      <div className="text-heading font-semibold text-ink">{title}</div>
      {children && <p className="mt-1 max-w-[52ch] text-body text-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ forms

const control =
  "w-full rounded-[var(--radius-control)] border border-line-strong bg-surface px-3 text-body text-ink placeholder:text-faint transition focus:border-primary focus:shadow-[0_0_0_3px_var(--primary-soft)] focus:outline-none disabled:opacity-60";

export const Input = ({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) => <input className={cx(control, "h-10", className)} {...props} />;
export const Textarea = ({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea className={cx(control, "min-h-24 py-2", className)} {...props} />;
export const Select = ({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) => <select className={cx(control, "h-10 pr-8", className)} {...props} />;

export function Field({ label, hint, children, className, error }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string; error?: ReactNode }) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1.5 block text-small font-semibold text-ink-2">{label}</span>
      {children}
      {hint && !error && <span className="mt-1 block text-small text-muted">{hint}</span>}
      {error && <span className="mt-1 block text-small text-error">{error}</span>}
    </label>
  );
}

/** An on/off switch with its label and an explanation. */
export function Toggle({ label, hint, checked, onChange, disabled }: { label: ReactNode; hint?: ReactNode; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return (
    <label className={cx("flex cursor-pointer items-start justify-between gap-4", disabled && "cursor-not-allowed opacity-60")}>
      <span className="min-w-0">
        <span className="block text-body font-medium text-ink">{label}</span>
        {hint && <span className="block text-small text-muted">{hint}</span>}
      </span>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cx("press relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors", checked ? "bg-primary" : "bg-surface-3 ring-1 ring-line-strong")}
      >
        <span className={cx("absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow-1 transition-transform duration-300 [transition-timing-function:cubic-bezier(0.2,0.9,0.3,1.4)]", checked && "translate-x-5")} />
      </button>
    </label>
  );
}

export function Checkbox({ label, hint, checked, onChange, disabled }: { label: ReactNode; hint?: ReactNode; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5">
      <input type="checkbox" className="mt-1 size-4 accent-[var(--primary)]" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span className="block text-body text-ink">{label}</span>
        {hint && <span className="block text-small text-muted">{hint}</span>}
      </span>
    </label>
  );
}

/** Pills where one is chosen. */
export function Segmented<T extends string | number>({ value, options, onChange, label, size = "md" }: { value: T; options: readonly (readonly [T, ReactNode])[]; onChange: (value: T) => void; label: string; size?: "sm" | "md" }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-xl bg-surface-3 p-1">
      {options.map(([key, text]) => (
        <button
          key={String(key)}
          type="button"
          role="radio"
          aria-checked={value === key}
          onClick={() => onChange(key)}
          className={cx(
            "press rounded-lg font-semibold transition",
            size === "sm" ? "h-7 px-2.5 text-small" : "h-9 px-4 text-body",
            value === key ? "bg-surface text-ink shadow-1" : "text-muted hover:text-ink",
          )}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd aria-hidden className="kbd">
      {children}
    </kbd>
  );
}

export function Avatar({ name, className }: { name: string; className?: string }) {
  const letters = name
    .replace(/https?:\/\/|www\./g, "")
    .split(/[\s.@-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0]!.toUpperCase())
    .join("");
  let hue = 0;
  for (const ch of name) hue = (hue * 31 + ch.charCodeAt(0)) % 360;
  return (
    <span
      aria-hidden
      className={cx("inline-flex size-9 shrink-0 items-center justify-center rounded-xl text-small font-bold", className)}
      style={{ background: `hsl(${hue} 70% 55% / 0.14)`, color: `hsl(${hue} 55% 45%)` }}
    >
      {letters || "?"}
    </span>
  );
}
