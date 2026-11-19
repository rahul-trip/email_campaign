/**
 * The shared building blocks of web2, styled with the Stitch design tokens (src/styles.css).
 * Pages compose these instead of repeating long class lists, so every screen looks and behaves
 * the same: one button family, one field style, one way to show loading, errors and saves.
 */
import { useMutation, useQuery, useQueryClient, type UseMutationResult, type UseQueryResult } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Check, ChevronDown, Loader2, X } from "lucide-react";
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type Dispatch,
  type InputHTMLAttributes,
  type KeyboardEvent,
  type ReactNode,
  type SelectHTMLAttributes,
  type SetStateAction,
  type TextareaHTMLAttributes,
} from "react";
import { ApiProblem, client, ok } from "../api/client";
import { isViewing, useCurrent } from "../app/session";
import { cx } from "../lib/cx";

// ------------------------------------------------------------------ buttons

type Variant = "primary" | "secondary" | "ghost" | "danger" | "danger-ghost";
type Size = "sm" | "md";

const variants: Record<Variant, string> = {
  primary: "bg-primary text-primary-ink hover:bg-primary",
  secondary: "border border-line-strong bg-surface text-ink hover:bg-surface-2",
  ghost: "text-muted hover:bg-surface-2 hover:text-ink",
  danger: "bg-error text-white hover:opacity-90",
  "danger-ghost": "text-error hover:bg-error-soft hover:text-error",
};
const sizes: Record<Size, string> = { sm: "h-8 px-3 text-small gap-1.5", md: "h-10 px-4 text-body gap-2" };

/** The class list of a button, for a router Link that should look like one. */
export const buttonClass = (variant: Variant = "primary", size: Size = "md", className?: string) =>
  cx(
    "inline-flex shrink-0 items-center justify-center press rounded-[10px] font-semibold whitespace-nowrap transition-colors outline-none focus-visible:ring-2 focus-visible:ring-primary/40 disabled:cursor-not-allowed disabled:opacity-45",
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

type SectionsState = { openId: string | null | undefined; setOpenId: Dispatch<SetStateAction<string | null | undefined>> };
const SectionsContext = createContext<SectionsState | null>(null);

/**
 * The collapsible cards inside it open one at a time: opening one closes the others. The first
 * card marked `defaultOpen` starts open. Cards outside a Sections keep their own state.
 */
export function Sections({ children }: { children: ReactNode }) {
  // undefined: nothing has been decided yet; null: every card is closed.
  const [openId, setOpenId] = useState<string | null | undefined>(undefined);
  const value = useMemo(() => ({ openId, setOpenId }), [openId]);
  return <SectionsContext.Provider value={value}>{children}</SectionsContext.Provider>;
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  tone,
  id,
  tour,
  collapsible = false,
  defaultOpen = false,
  forceOpen = false,
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
  /** The header opens and closes the body. The subtitle stays visible, so it can summarise. */
  collapsible?: boolean;
  /** A collapsible card starts open (it starts closed by default). */
  defaultOpen?: boolean;
  /** Turning this on opens the card (the reader can still close it afterwards). */
  forceOpen?: boolean;
}) {
  const sections = useContext(SectionsContext);
  const self = useId();
  const grouped = sections !== null && collapsible;
  const [ownOpen, setOwnOpen] = useState(defaultOpen || forceOpen);
  const open = grouped ? sections.openId === self : ownOpen;
  const setOpen = (next: boolean) => {
    if (!grouped) return setOwnOpen(next);
    if (next) sections.setOpenId(self);
    else sections.setOpenId((prev) => (prev === self ? null : prev));
  };
  const body = useId();
  // Only the first defaultOpen card in a group takes the open slot, and only if none was chosen.
  useEffect(() => {
    if (grouped && defaultOpen) sections.setOpenId((prev) => (prev === undefined ? self : prev));
    // Mount only: the group's first decision is the default.
  }, []);
  useEffect(() => {
    if (!forceOpen) return;
    if (grouped) sections.setOpenId(self);
    else setOwnOpen(true);
    // Runs when forceOpen turns on; the reader can still close it afterwards.
  }, [forceOpen]);
  const shown = !collapsible || open;
  return (
    <section
      id={id}
      data-tour={tour}
      className={cx(
        "card p-5",
        tone === "attention" ? "border-attention/50" : tone === "error" ? "border-error/40" : "border-line",
        className,
      )}
    >
      {(title || actions) && (
        <header className={cx("flex flex-wrap items-start justify-between gap-2", shown && "mb-3")}>
          {collapsible ? (
            <button type="button" aria-expanded={open} aria-controls={body} onClick={() => setOpen(!open)} className="flex min-w-0 flex-1 items-start gap-2 text-left">
              <ChevronDown aria-hidden className={cx("mt-1 size-4 shrink-0 text-muted transition-transform", !open && "-rotate-90")} />
              <span className="min-w-0">
                {title && <h2 className="text-heading font-semibold text-ink">{title}</h2>}
                {subtitle && <p className="mt-0.5 text-small font-normal text-muted">{subtitle}</p>}
              </span>
            </button>
          ) : (
            <div className="min-w-0">
              {title && <h2 className="text-heading font-semibold text-ink">{title}</h2>}
              {subtitle && <p className="mt-0.5 text-small text-muted">{subtitle}</p>}
            </div>
          )}
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      {shown && <div id={body}>{children}</div>}
    </section>
  );
}

export function PageHeader({ title, subtitle, actions, crumbs }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; crumbs?: ReactNode }) {
  return (
    <div className="mb-8 animate-rise">
      {crumbs && <div className="mb-2 text-small text-muted">{crumbs}</div>}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[1.75rem] leading-9 font-semibold tracking-tight text-ink">{title}</h1>
          {subtitle && <div className="mt-1.5 max-w-[65ch] text-body text-muted">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

/** A small uppercase label above a group of content. */
export const Label = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={cx("text-label font-semibold uppercase tracking-wider text-muted", className)}>{children}</div>
);

/** One number with its label, for the summary rows at the top of a page. */
export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "attention" | "error" | "good" | "primary" }) {
  const colour = { attention: "text-attention", error: "text-error", good: "text-good", primary: "text-ink" };
  return (
    <div className="card card-hover relative overflow-hidden p-5">
      <div className="text-small font-medium text-muted">{label}</div>
      <div className={cx("tnum mt-2 text-[2rem] leading-10 font-semibold tracking-tight", tone ? colour[tone] : "text-ink")}>{value}</div>
      {hint && <div className="mt-1 text-small text-muted">{hint}</div>}
    </div>
  );
}

/** A short definition list: label on the left, value on the right. */
export function Facts({ facts }: { facts: { label: ReactNode; value: ReactNode }[] }) {
  return (
    <dl className="divide-y divide-line rounded-lg border border-line">
      {facts.map((fact, index) => (
        <div key={index} className="grid grid-cols-[minmax(7rem,40%)_minmax(0,1fr)] gap-3 px-3 py-2 text-small">
          <dt className="text-muted">{fact.label}</dt>
          <dd className="min-w-0 text-ink [overflow-wrap:anywhere]">{fact.value}</dd>
        </div>
      ))}
    </dl>
  );
}

// ------------------------------------------------------------------ form fields

const field =
  "rounded-lg border border-line-strong bg-surface-2 px-2.5 text-body text-ink outline-none transition placeholder:text-muted/70 focus:border-primary focus:bg-surface focus:ring-2 focus:ring-primary/20 disabled:opacity-60";

/** Full width unless the page gives the control a width of its own. */
const width = (className?: string) => (className && /(^|\s)(w-|min-w-|max-w-)/.test(className) ? "" : "w-full");

export const Input = ({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) => (
  <input className={cx(field, width(className), "h-10", className)} {...props} />
);
export const Textarea = ({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) => (
  <textarea className={cx(field, width(className), "resize-y py-2 leading-relaxed", className)} {...props} />
);
export const Select = ({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) => (
  <select className={cx(field, width(className), "h-10 cursor-pointer pr-7", className)} {...props} />
);

/** A labelled field. The label wraps the control, so it is announced and clickable. */
export function Field({ label, hint, children, className }: { label: ReactNode; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="mb-1 block text-small font-medium text-ink">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-label leading-snug text-muted">{hint}</span>}
    </label>
  );
}

export function Checkbox({ label, hint, checked, onChange, disabled }: { label: ReactNode; hint?: ReactNode; checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return (
    <label className={cx("flex items-start gap-2 text-body", disabled ? "opacity-60" : "cursor-pointer")}>
      <input type="checkbox" className="mt-0.5 size-4 accent-[var(--primary)]" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span className="font-medium">{label}</span>
        {hint && <span className="block text-label text-muted">{hint}</span>}
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
    <div role="alert" className={cx("rounded-lg border border-error/30 bg-error-soft px-3 py-2 text-small text-error", className)}>
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
    info: "border-primary-line bg-primary-soft text-ink",
    attention: "border-attention/40 bg-attention-soft text-attention",
    error: "border-error/30 bg-error-soft text-error",
    good: "border-good/30 bg-good-soft text-good",
  };
  return (
    <div className={cx("flex gap-3 rounded-xl border px-4 py-3 text-body", tones[tone], className)}>
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
      <span role="status" className="text-small text-muted">
        Saving…
      </span>
    );
  if (mutation.error) return <Problem error={mutation.error} />;
  if (mutation.isSuccess && shown)
    return (
      <span role="status" className="inline-flex items-center gap-1 text-small font-medium text-good">
        <Check aria-hidden className="size-3.5" /> {done}
      </span>
    );
  return null;
}

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

/** Loading and error handling for a query, so no page shows a blank screen while it waits or fails. */
export function QueryState<T>({ query, children, rows, shape }: { query: UseQueryResult<T>; children: (data: T) => ReactNode; rows?: number; shape?: SkeletonShape }) {
  if (query.isPending) return <Skeleton rows={rows} shape={shape} />;
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
      {icon && <div className="mb-3 text-muted">{icon}</div>}
      {title && <div className="text-heading font-semibold text-ink">{title}</div>}
      {children && <div className="mt-1 max-w-md text-small text-muted">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

// ------------------------------------------------------------------ tables

export const Table = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={cx("relative overflow-x-auto", className)}>
    <table className="w-full border-collapse text-left text-body">{children}</table>
  </div>
);
export const Th = ({ children, className }: { children?: ReactNode; className?: string }) => (
  <th scope="col" className={cx("border-b border-line px-4 py-3 text-label font-semibold tracking-wide text-faint uppercase", className)}>
    {children}
  </th>
);
export const Td = ({ children, className, colSpan }: { children?: ReactNode; className?: string; colSpan?: number }) => (
  <td colSpan={colSpan} className={cx("border-b border-line px-4 py-3 align-middle", className)}>
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
      <div role="tablist" aria-label={label} data-tour={tour} className="mb-6 flex gap-1 overflow-x-auto border-b border-line">
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
              "-mb-px inline-flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-body font-semibold whitespace-nowrap outline-none transition-colors focus-visible:ring-2 focus-visible:ring-primary/40",
              value === id ? "border-primary text-ink" : "border-transparent text-muted hover:text-ink",
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
    <div role="radiogroup" aria-label={label} className="inline-flex flex-wrap rounded-xl bg-surface-3 p-1">
      {options.map(([id, text]) => (
        <button
          key={String(id)}
          type="button"
          role="radio"
          aria-checked={value === id}
          onClick={() => onChange(id)}
          className={cx("press rounded-lg px-3 py-1.5 text-small font-semibold transition", value === id ? "bg-surface text-ink shadow-1" : "text-muted hover:text-ink")}
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
      <div ref={box} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} className="flex max-h-[calc(100dvh-2rem)] w-full max-w-md flex-col rounded-xl border border-line bg-surface shadow-xl outline-none">
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <h2 id={titleId} className={cx("text-base font-semibold", tone === "danger" && "text-error")}>
            {title}
          </h2>
          <button type="button" data-close aria-label="Close" onClick={onClose} className="rounded-md p-1 text-muted hover:bg-surface-2 hover:text-ink">
            <X className="size-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-5 py-4 text-body">{children}</div>
        {footer && <div className="flex shrink-0 justify-end gap-2 border-t border-line px-5 py-3">{footer}</div>}
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

// ------------------------------------------------------------------ menus

/** A person's initials in a circle. */
export function Avatar({ name, className }: { name: string; className?: string }) {
  const initials =
    name
      .split(/[\s@._-]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0]!.toUpperCase())
      .join("") || "?";
  return (
    <span aria-hidden className={cx("flex size-7 shrink-0 items-center justify-center rounded-full bg-primary-soft text-label font-semibold text-primary", className)}>
      {initials}
    </span>
  );
}

export type MenuItem = { label: ReactNode; onSelect: () => void; hint?: ReactNode; current?: boolean; tone?: "danger" };

/**
 * A button that opens a short list of actions. Arrow keys move, Enter picks, Escape or a click
 * outside closes it, and focus returns to the button.
 */
export function Menu({ label, button, items, header, align = "right", tour, buttonClassName }: { label: string; button: ReactNode; items: MenuItem[]; header?: ReactNode; align?: "left" | "right"; tour?: string; buttonClassName?: string }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    root.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    const away = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [open]);
  const close = () => {
    setOpen(false);
    trigger.current?.focus();
  };
  const onKey = (event: KeyboardEvent<HTMLDivElement>) => {
    const entries = Array.from(root.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? []);
    const at = entries.indexOf(document.activeElement as HTMLElement);
    if (event.key === "Escape") close();
    else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      entries[(at + step + entries.length) % entries.length]?.focus();
    }
  };
  return (
    <div ref={root} className="relative" onKeyDown={onKey} data-tour={tour}>
      <button ref={trigger} type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => setOpen(!open)} className={buttonClassName}>
        {button}
      </button>
      {open && (
        <div id={id} role="menu" aria-label={label} className={cx("glass absolute top-full z-50 mt-2 min-w-56 animate-rise overflow-hidden rounded-xl border border-line p-1.5 shadow-3", align === "right" ? "right-0" : "left-0")}>
          {header && <div className="border-b border-line px-3 py-2 text-small">{header}</div>}
          {items.map((item, index) => (
            <button
              key={index}
              type="button"
              role="menuitem"
              aria-current={item.current || undefined}
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={cx("flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-body outline-none hover:bg-surface-2 focus:bg-surface-2", item.tone === "danger" ? "text-error" : "text-ink", item.current && "font-semibold")}
            >
              <span className="flex items-center gap-2">{item.label}</span>
              {item.hint && <span className="text-label text-muted">{item.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** "Start now" for work that waits for the next run. The worker also moves everything due every
 * 15 minutes, so this only saves the wait. It says so when a run is already working. */
export function StartNow({ label = "Start now" }: { label?: string }) {
  const { workspace } = useCurrent();
  const queryClient = useQueryClient();
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: () => ok(client.GET("/api/runs")),
    refetchInterval: (query) => (query.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 2000 : 10000),
  });
  const start = useMutation({
    mutationFn: () => ok(client.POST("/api/runs", { body: { mode: "manual" } })),
    onSuccess: () => {
      for (const key of ["runs", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  if (isViewing(workspace)) return null;
  if (start.data)
    return (
      <span className="text-small text-good" role="status">
        Started.{" "}
        <Link to="/runs/$runId" params={{ runId: start.data.id }} className="font-semibold underline">
          Follow it
        </Link>
      </span>
    );
  if (runs.data?.some((r) => r.status === "queued" || r.status === "running"))
    return <span className="text-small text-muted">A run is already working; it, or the next one, picks this up.</span>;
  return (
    <>
      <Button size="sm" variant="secondary" busy={start.isPending} onClick={() => start.mutate()}>
        {label}
      </Button>
      <Problem error={start.error} />
    </>
  );
}
