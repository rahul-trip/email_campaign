/**
 * The small controls every filterable list uses: a search box, toggle chips and a sort menu.
 * Leads, LinkedIn ready and Needs a decision share them so they look and behave the same.
 */
import { ArrowDown, ArrowUp, ChevronDown, Search, SlidersHorizontal } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";
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

/**
 * The bar above a filterable list. From a tablet up everything sits in the open, as it always did.
 * On a phone it is one line, the search and a Filters button that says how many are on; the
 * chips, menus and sort fold open underneath. ``active`` counts the filters that are on (not the search).
 */
export function FilterBar({ search, active, controls, trailing }: { search: ReactNode; active: number; controls: ReactNode; trailing: ReactNode }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <div className="flex flex-col gap-2 bg-surface-2 p-3 sm:flex-row sm:flex-wrap sm:items-center">
      <div className="flex items-center gap-2 sm:contents">
        {search}
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          onClick={() => setOpen(!open)}
          className={cx("press inline-flex h-10 shrink-0 items-center gap-1.5 rounded-[var(--radius-control)] border px-3 text-small font-semibold sm:hidden", active > 0 ? "border-primary bg-primary-soft text-primary" : "border-line-strong bg-surface text-ink-2")}
        >
          <SlidersHorizontal className="size-4" aria-hidden /> Filters
          {active > 0 && <span className="tnum flex size-5 items-center justify-center rounded-full bg-primary text-label text-primary-ink">{active}</span>}
          <ChevronDown className={cx("size-4 transition-transform", open && "rotate-180")} aria-hidden />
        </button>
      </div>
      <div id={panel} className={cx("flex-wrap items-center gap-2 sm:flex [&>select]:w-auto [&>select]:min-w-[8rem] [&>select]:flex-1 sm:[&>select]:flex-none", open ? "flex" : "hidden")}>
        {controls}
      </div>
      <div className={cx("flex-wrap items-center gap-2 sm:ml-auto sm:flex", open ? "flex" : "hidden")}>{trailing}</div>
    </div>
  );
}
