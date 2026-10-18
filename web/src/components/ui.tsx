import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";
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

export function Card({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-line bg-panel p-4", className)}>
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
