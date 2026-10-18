import type { UseMutationResult, UseQueryResult } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import type { ButtonHTMLAttributes, InputHTMLAttributes, KeyboardEvent, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
import { ApiProblem } from "../api/client";

const cx = (...parts: (string | false | undefined)[]) => parts.filter(Boolean).join(" ");

type Variant = "primary" | "secondary" | "danger" | "ghost";
const variants: Record<Variant, string> = {
  primary: "bg-brand text-white hover:opacity-90",
  secondary: "border border-line bg-white hover:bg-gray-50",
  danger: "bg-red-600 text-white hover:opacity-90",
  ghost: "hover:bg-gray-100",
};

export function Button({
  variant = "primary",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
        variants[variant],
        className,
      )}
      {...props}
    />
  );
}

/** ``tour`` names the card for the guided tour (see src/tour/steps.ts). */
export function Card({ title, actions, children, className, tour }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; tour?: string }) {
  return (
    <section data-tour={tour} className={cx("rounded-lg border border-line bg-panel p-4", className)}>
      {(title || actions) && (
        <header className="mb-3 flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">{title}</h2>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

const tones: Record<string, string> = {
  gray: "bg-gray-100 text-gray-700",
  green: "bg-green-100 text-green-800",
  amber: "bg-amber-100 text-amber-800",
  red: "bg-red-100 text-red-800",
  blue: "bg-blue-100 text-blue-800",
};

export function Badge({ tone = "gray", children }: { tone?: keyof typeof tones; children: ReactNode }) {
  return <span className={cx("inline-block rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>{children}</span>;
}

export function statusTone(status: string): keyof typeof tones {
  if (["failed", "rejected", "disqualified", "suppressed", "cancelled"].includes(status)) return "red";
  if (["held", "needs_confirmation", "pending", "queued"].includes(status)) return "amber";
  if (["copy_ready", "approved", "in_sequence", "completed", "succeeded", "accepted"].includes(status)) return "green";
  if (["running"].includes(status)) return "blue";
  return "gray";
}

const field = "w-full rounded-md border border-line bg-white px-2.5 py-1.5 text-sm outline-none focus:border-brand";

export const Input = (props: InputHTMLAttributes<HTMLInputElement>) => <input className={field} {...props} />;
export const Textarea = (props: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea className={cx(field, "font-mono")} {...props} />;
export const Select = (props: SelectHTMLAttributes<HTMLSelectElement>) => <select className={field} {...props} />;

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-muted">{hint}</span>}
    </label>
  );
}

export function Problem({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 p-2 text-sm text-red-800">
      {message}
      {error instanceof ApiProblem && error.fields.length > 0 && (
        <ul className="mt-1 list-disc pl-5">
          {error.fields.map((f) => (
            <li key={f.field}>
              {f.field}: {f.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * What happened to the last save, next to the Save button: "Saving…", then a green "Saved" that
 * fades after a few seconds, or the error. Without it a save looks like a button that does nothing.
 */
export function SaveNote({ mutation, done = "Saved." }: { mutation: Pick<UseMutationResult<unknown, Error, never>, "isPending" | "isSuccess" | "error" | "submittedAt">; done?: string }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (!mutation.isSuccess) return;
    setShown(true);
    const timer = window.setTimeout(() => setShown(false), 5000);
    return () => window.clearTimeout(timer);
  }, [mutation.isSuccess, mutation.submittedAt]);
  if (mutation.isPending) return <span role="status" className="text-sm text-muted">Saving…</span>;
  if (mutation.error) return <Problem error={mutation.error} />;
  if (mutation.isSuccess && shown)
    return (
      <span role="status" className="text-sm font-medium text-green-700">
        ✓ {done}
      </span>
    );
  return null;
}

/** Loading and error handling for a query, so no page shows a blank screen while it waits or fails. */
export function QueryState<T>({ query, children }: { query: UseQueryResult<T>; children: (data: T) => ReactNode }) {
  if (query.isPending)
    return (
      <p role="status" className="py-6 text-center text-sm text-muted">
        Loading…
      </p>
    );
  if (query.isError)
    return (
      <div className="space-y-2">
        <Problem error={query.error} />
        <Button variant="secondary" onClick={() => void query.refetch()}>
          Try again
        </Button>
      </div>
    );
  return <>{children(query.data)}</>;
}

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
  tabs: readonly (readonly [T, string])[];
  value: T;
  onChange: (id: T) => void;
  children: ReactNode;
}) {
  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const target =
      event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : -1;
    if (target < 0) return;
    event.preventDefault();
    onChange(tabs[target][0]);
    document.getElementById(`tab-${tabs[target][0]}`)?.focus();
  };
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label={label} data-tour={tour} className="flex flex-wrap gap-1">
        {tabs.map(([id, text], index) => (
          <button
            key={id}
            id={`tab-${id}`}
            role="tab"
            aria-selected={value === id}
            aria-controls={`panel-${id}`}
            tabIndex={value === id ? 0 : -1}
            onClick={() => onChange(id)}
            onKeyDown={(event) => move(event, index)}
            className={cx("rounded-md px-3 py-1.5 text-sm outline-none focus-visible:ring-2 focus-visible:ring-brand", value === id ? "bg-brand text-white" : "bg-white hover:bg-gray-100")}
          >
            {text}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`panel-${value}`} aria-labelledby={`tab-${value}`}>
        {children}
      </div>
    </div>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => <p className="py-6 text-center text-sm text-muted">{children}</p>;

export const Table = ({ children }: { children: ReactNode }) => (
  <div className="overflow-x-auto">
    <table className="w-full text-left text-sm">{children}</table>
  </div>
);
export const Th = ({ children }: { children?: ReactNode }) => <th className="border-b border-line px-2 py-1.5 text-xs font-semibold uppercase tracking-wide text-muted">{children}</th>;
export const Td = ({ children, className }: { children?: ReactNode; className?: string }) => <td className={cx("border-b border-line px-2 py-1.5 align-top", className)}>{children}</td>;

/** Micro-dollars (1,000,000 = $1) as dollars. */
export const usd = (micro: number, places = 4) => `$${(micro / 1_000_000).toFixed(places)}`;
export const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : "");
export const words = (text: string) => text.replaceAll("_", " ");
