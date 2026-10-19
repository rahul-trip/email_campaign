/**
 * The shared building blocks of web2, styled with the Stitch design tokens (src/styles.css).
 * Pages compose these instead of repeating long class lists, so every screen looks and behaves
 * the same: one button family, one field style, one way to show loading, errors and saves.
 */
import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import { Check, Loader2, X } from "lucide-react";
import {
  useEffect,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { ApiProblem } from "../api/client";
import { cx } from "../lib/cx";

// ------------------------------------------------------------------ buttons

type Variant = "primary" | "secondary" | "ghost" | "danger" | "danger-ghost";
type Size = "sm" | "md";

const variants: Record<Variant, string> = {
  primary: "bg-primary-container text-on-primary hover:bg-primary",
  secondary: "border border-outline bg-surface text-ink hover:bg-surface-low",
  ghost: "text-muted hover:bg-surface-low hover:text-ink",
  danger: "bg-error text-white hover:opacity-90",
  "danger-ghost": "text-error hover:bg-error-container hover:text-on-error-container",
};
const sizes: Record<Size, string> = { sm: "h-7 px-2.5 text-xs gap-1", md: "h-8 px-3 text-[13px] gap-1.5" };

/** The class list of a button, for a router Link that should look like one. */
export const buttonClass = (variant: Variant = "primary", size: Size = "md", className?: string) =>
  cx(
    "inline-flex shrink-0 items-center justify-center rounded-lg font-semibold whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-primary-container/40 disabled:cursor-not-allowed disabled:opacity-45",
    variants[variant],
    sizes[size],
    className,
  );

export function Button({
  variant = "primary",
  size = "md",
  busy = false,
  className,
  children,
  disabled,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size; busy?: boolean }) {
  return (
    <button type={type} className={buttonClass(variant, size, className)} disabled={disabled || busy} {...props}>
      {busy && <Loader2 aria-hidden className="size-3.5 animate-spin" />}
      {children}
    </button>
  );
}

// ------------------------------------------------------------------ layout

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  tone,
  id,
  tour,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  tone?: "attention" | "error";
  id?: string;
  /** Names the card for the guided tour (src/tour/steps.ts). */
  tour?: string;
}) {
  return (
    <section
      id={id}
      data-tour={tour}
      className={cx(
        "rounded-xl border bg-surface p-4",
        tone === "attention" ? "border-attention/50" : tone === "error" ? "border-error/40" : "border-line",
        className,
      )}
    >
      {(title || actions) && (
        <header className="mb-3 flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            {title && <h2 className="text-[15px] font-semibold leading-snug">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, actions, crumbs }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; crumbs?: ReactNode }) {
  return (
    <div className="mb-5">
      {crumbs && <div className="mb-2 text-xs text-muted">{crumbs}</div>}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-0.5 text-muted">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

/** A small uppercase label above a group of content. */
export const Label = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={cx("text-[11px] font-semibold uppercase tracking-wider text-muted", className)}>{children}</div>
);

/** One number with its label, for the summary rows at the top of a page. */
export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "attention" | "error" | "good" | "primary" }) {
  const colour = { attention: "text-attention", error: "text-error", good: "text-good", primary: "text-primary" };
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <Label>{label}</Label>
      <div className={cx("mt-1 text-[26px] font-semibold leading-8", tone && colour[tone])}>{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
    </div>
  );
}

/** A short definition list: label on the left, value on the right. */
export function Facts({ facts }: { facts: { label: ReactNode; value: ReactNode }[] }) {
  return (
    <dl className="divide-y divide-line rounded-lg border border-line">
      {facts.map((fact, index) => (
        <div key={index} className="grid grid-cols-[minmax(7rem,40%)_1fr] gap-3 px-3 py-2 text-xs">
          <dt className="text-muted">{fact.label}</dt>
          <dd className="break-words text-ink">{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}

// ------------------------------------------------------------------ form fields

const field =
  "rounded-lg border border-outline bg-surface-low px-2.5 text-[13px] text-ink outline-none transition placeholder:text-muted/70 focus:border-primary-container focus:bg-surface focus:ring-2 focus:ring-primary-container/20 disabled:opacity-60";

/** Full width unless the page gives the control a width of its own. */
const width = (className?: string) => (className && /(^|\s)(w-|min-w-|max-w-)/.test(className) ? "" : "w-full");

export const Input = ({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) => (
  <input className={cx(field, width(className), "h-8", className)} {...props} />
);
export const Textarea = ({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <textarea className={cx(field, width(className), "resize-y py-2 leading-relaxed", className)} {...props} />
);
export const Select = ({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select className={cx(field, width(className), "h-8 cursor-pointer pr-7", className)} {...props} />
);

/** A labelled field. The label wraps the control, so it is announced and clickable. */
export function Field({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1 block text-xs font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] leading-snug text-muted">{hint}</span>}
    </label>
  );
}

export function Checkbox({ label, hint, checked, onChange, disabled }: { label: ReactNode; hint?: ReactNode; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return (
    <label className={cx("flex items-start gap-2 text-[13px]", disabled ? "opacity-60" : "cursor-pointer")}>
      <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary-container)]" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span className="font-medium">{label}</span>
        {hint && <span className="block text-[11px] text-muted">{hint}</span>}
      </span>
    </label>
  );
}

// ------------------------------------------------------------------ feedback

/** An API error in plain words, with any field errors and the request reference. */
export function Problem({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className={cx("rounded-lg border border-error/30 bg-error-container px-3 py-2 text-xs text-on-error-container", className)}>
      {message}
      {error instanceof ApiProblem && error.status === 409 && <span className="mt-0.5 block font-medium">Someone or something changed this since you opened it. Reload and try again.</span>}
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
  );
}

/** A coloured note: an explanation, a warning or a success, inside a page. */
export function Callout({ tone = "info", title, children, icon, className }: { tone?: "info" | "attention" | "error" | "good"; title?: ReactNode; children?: ReactNode; icon?: ReactNode; className?: string }) {
  const tones = {
    info: "border-primary-container/25 bg-primary-fixed/50 text-ink",
    attention: "border-attention/40 bg-attention-container text-on-attention-container",
    error: "border-error/30 bg-error-container text-on-error-container",
    good: "border-good/30 bg-good-container text-on-good-container",
  };
  return (
    <div className={cx("flex gap-2.5 rounded-lg border px-3 py-2.5 text-xs leading-relaxed", tones[tone], className)}>
      {icon && <span className="mt-0.5 shrink-0">{icon}</span>}
      <div className="min-w-0">
        {title && <div className="font-semibold">{title}</div>}
        {children}
      </div>
    </div>
  );
}

/**
 * What happened to the last save, next to its button: "Saving…", then a tick that fades after a
 * few seconds, or the error. Without it a save looks like a button that does nothing.
 */
export function SaveNote({ mutation, done = "Saved." }: { mutation: Pick<UseMutationResult<unknown, Error, never>, "isPending" | "isSuccess" | "error" | "submittedAt">; done?: string }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!mutation.isSuccess) return;
    setShown(true);
    const timer = window.setTimeout(() => setShown(false), 5000);
    return () => window.clearTimeout(timer);
  }, [mutation.isSuccess, mutation.submittedAt]);
  if (mutation.isPending)
    return (
      <span role="status" className="text-xs text-muted">
        Saving…
      </span>
    );
  if (mutation.error) return <Problem error={mutation.error} />;
  if (mutation.isSuccess && shown)
    return (
      <span role="status" className="inline-flex items-center gap-1 text-xs font-medium text-good">
        <Check aria-hidden className="size-3.5" /> {done}
      </span>
    );
  return null;
}

/** Grey placeholder bars while something loads. */
export function Skeleton({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div role="status" aria-label="Loading" className={cx("space-y-2 py-2", className)}>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-4 animate-pulse rounded bg-surface-container" style={{ width: `${92 - i * 11}%` }} />
      ))}
    </div>
  );
}

/** Loading and error handling for a query, so no page shows a blank screen while it waits or fails. */
export function QueryState<T>({ query, children, rows }: { query: UseQueryResult<T>; children: (data: T) => ReactNode; rows?: number }) {
  if (query.isPending) return <Skeleton rows={rows} />;
  if (query.isError)
    return (
      <div className="space-y-2">
        <Problem error={query.error} />
        <Button variant="secondary" size="sm" onClick={() => void query.refetch()}>
          Try again
        </Button>
      </div>
    );
  return <>{children(query.data)}</>;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title?: ReactNode; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
      {icon && <div className="mb-2 text-muted">{icon}</div>}
      {title && <div className="text-sm font-semibold">{title}</div>}
      {children && <div className="mt-1 max-w-md text-xs text-muted">{children}</div>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ tables

export const Table = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={cx("relative overflow-x-auto", className)}>
    <table className="w-full border-collapse text-left text-[13px]">{children}</table>
  </div>
);
export const Th = ({ children, className }: { children?: ReactNode; className?: string }) => (
  <th scope="col" className={cx("border-b border-line bg-surface-low px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-muted", className)}>
    {children}
  </th>
);
export const Td = ({ children, className, colSpan }: { children?: ReactNode; className?: string; colSpan?: number }) => (
  <td colSpan={colSpan} className={cx("border-b border-line px-3 py-2.5 align-middle", className)}>
    {children}
  </td>
);

// ------------------------------------------------------------------ tabs

/** Tabs that follow the ARIA pattern: arrow keys, Home and End move between them. */
export function Tabs<T extends string>({
  label,
  tabs,
  value,
  onChange,
  children,
  tour,
}: {
  label: string;
  tour?: string;
  tabs: readonly (readonly [T, ReactNode])[];
  value: T;
  onChange: (id: T) => void;
  children: ReactNode;
}) {
  const base = useId();
  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const target =
      event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
    if (target < 0) return;
    event.preventDefault();
    onChange(tabs[target][0]);
    document.getElementById(`${base}-tab-${tabs[target][0]}`)?.focus();
  };
  return (
    <div>
      <div role="tablist" aria-label={label} data-tour={tour} className="mb-5 flex flex-wrap gap-1 border-b border-line">
        {tabs.map(([id, text], index) => (
          <button
            key={id}
            id={`${base}-tab-${id}`}
            type="button"
            role="tab"
            aria-selected={value === id}
            aria-controls={`${base}-panel`}
            tabIndex={value === id ? 0 : -1}
            onClick={() => onChange(id)}
            onKeyDown={(event) => move(event, index)}
            className={cx(
              "-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2 text-[13px] font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary-container/40",
              value === id ? "border-primary-container text-primary" : "border-transparent text-muted hover:text-ink",
            )}
          >
            {text}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`${base}-panel`} aria-labelledby={`${base}-tab-${value}`}>
        {children}
      </div>
    </div>
  );
}

/** A row of mutually exclusive choices, for filters and periods. */
export function Segmented<T extends string | number>({ value, options, onChange, label }: { value: T; options: readonly (readonly [T, ReactNode])[]; onChange: (value: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-lg border border-line bg-surface-low p-0.5">
      {options.map(([id, text]) => (
        <button
          key={String(id)}
          type="button"
          role="radio"
          aria-checked={value === id}
          onClick={() => onChange(id)}
          className={cx("rounded-md px-2.5 py-1 text-xs font-medium transition-colors", value === id ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink")}
        >
          {text}
        </button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ dialogs

/** A modal dialog. Escape and the backdrop close it; focus starts inside and returns after. */
export function Dialog({ title, children, onClose, footer, tone }: { title: ReactNode; children: ReactNode; onClose: () => void; footer?: ReactNode; tone?: "danger" }) {
  const box = useRef<HTMLDivElement>(null);
  const titleId = useId();
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const first = box.current?.querySelector<HTMLElement>("input, textarea, select, button:not([data-close])");
    (first ?? box.current)?.focus();
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      before?.focus();
    };
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={box} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="w-full max-w-md rounded-xl border border-line bg-surface shadow-xl outline-none">
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <h2 id={titleId} className={cx("text-base font-semibold", tone === "danger" && "text-error")}>
            {title}
          </h2>
          <button type="button" data-close aria-label="Close" onClick={onClose} className="rounded-md p-1 text-muted hover:bg-surface-low hover:text-ink">
            <X className="size-4" />
          </button>
        </div>
        <div className="space-y-3 px-5 py-4 text-[13px]">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
      </div>
    </div>
  );
}

/**
 * A yes-or-no question before something that cannot be undone. With ``typed``, the person must
 * type that text first (the server checks it again where it matters).
 */
export function Confirm({
  title,
  children,
  confirmLabel,
  onConfirm,
  onClose,
  busy,
  error,
  typed,
}: {
  title: ReactNode;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: (typedText: string) => void;
  onClose: () => void;
  busy?: boolean;
  error?: unknown;
  typed?: string;
}) {
  const [text, setText] = useState("");
  const ready = !typed || text.trim().toLowerCase() === typed.toLowerCase();
  return (
    <Dialog
      title={title}
      tone="danger"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" busy={busy} disabled={!ready} onClick={() => onConfirm(text.trim())}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
      {typed && (
        <Field label={`Type ${typed} to confirm`}>
          <Input value={text} onChange={(e) => setText(e.target.value)} placeholder={typed} autoComplete="off" spellCheck={false} />
        </Field>
      )}
      <Problem error={error} />
    </Dialog>
  );
}
