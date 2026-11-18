/**
 * The small controls every filterable list uses: a search box, toggle chips and a sort menu.
 * Leads, Hot leads and Needs a decision share them so they look and behave the same.
 */
import { ArrowDown, ArrowUp, Search } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cx } from "../lib/cx";
import { Button, Select } from "./core";

/** A value that follows ``value`` after it has stopped changing for ``ms``. */
export function useDebounced<T>(value: T, ms = 300): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), ms);
    return () => window.clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

export function SearchBox({ value, onChange, label, placeholder }: { value: string; onChange: (value: string) => void; label: string; placeholder: string }) {
  return (
    <div className="relative min-w-[200px] flex-1 sm:max-w-sm">
      <Search className="absolute top-3 left-3 size-4 text-faint" aria-hidden />
      <input
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-10 w-full rounded-[var(--radius-control)] border border-line-strong bg-surface pr-3 pl-9 text-body text-ink outline-none focus:border-primary focus:shadow-[0_0_0_3px_var(--primary-soft)]"
      />
    </div>
  );
}

/** A pill that switches a filter on and off. ``count`` is shown when the filter would match that many. */
export function FilterChip({ active, onClick, children, count }: { active: boolean; onClick: () => void; children: ReactNode; count?: number }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cx("press inline-flex h-9 items-center gap-1.5 rounded-full border px-3.5 text-small font-semibold", active ? "border-primary bg-primary-soft text-primary" : "border-line-strong bg-surface text-ink-2 hover:text-ink")}
    >
      {children}
      {count !== undefined && <span className="tnum text-muted">{count}</span>}
    </button>
  );
}

/** A sort menu with a button to reverse it. */
export function SortControl<T extends string>({ value, options, direction, onSort, onDirection }: { value: T; options: readonly (readonly [T, string])[]; direction: "asc" | "desc"; onSort: (value: T) => void; onDirection: () => void }) {
  return (
    <div className="flex items-center gap-1">
      <Select aria-label="Sort by" value={value} onChange={(e) => onSort(e.target.value as T)} className="min-w-0 flex-1 sm:w-auto sm:flex-none">
        {options.map(([key, label]) => (
          <option key={key} value={key}>
            Sort: {label}
          </option>
        ))}
      </Select>
      <Button variant="secondary" aria-label={`Sort direction: ${direction === "asc" ? "ascending" : "descending"}`} title="Reverse the order" onClick={onDirection} className="h-10 px-3">
        {direction === "asc" ? <ArrowUp className="size-4" aria-hidden /> : <ArrowDown className="size-4" aria-hidden />}
      </Button>
    </div>
  );
}
