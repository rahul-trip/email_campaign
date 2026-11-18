/**
 * Collapsible sections, the page rule for web3: every section can fold, the first is open by
 * default, the rest closed, each shows a one-line summary while closed, and a group offers
 * "Expand all / Collapse all". A section remembers its state for this browser per page.
 */
import { ChevronDown, ChevronsDownUp, ChevronsUpDown } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "../lib/cx";

type Group = {
  register: (id: string) => number;
  isOpen: (id: string, index: number) => boolean;
  set: (id: string, open: boolean) => void;
  version: number;
};
const GroupContext = createContext<Group | null>(null);

function stored(key: string): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "{}") as Record<string, boolean>;
  } catch {
    return {};
  }
}

/**
 * Wraps a page's sections. ``storageKey`` names the page so a person's choices are kept; the
 * page works the same without storage (private windows).
 */
export function SectionGroup({ storageKey, children, className, toolbar = true }: { storageKey: string; children: ReactNode; className?: string; toolbar?: boolean }) {
  const key = `outbound.sections.${storageKey}`;
  const order = useRef<string[]>([]);
  const [state, setState] = useState<Record<string, boolean>>(() => stored(key));
  const [version, setVersion] = useState(0);

  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(state));
    } catch {
      // storage blocked: the choice lasts for this visit
    }
  }, [key, state]);

  const register = useCallback((id: string) => {
    if (!order.current.includes(id)) order.current.push(id);
    return order.current.indexOf(id);
  }, []);
  const isOpen = useCallback((id: string, index: number) => (id in state ? state[id]! : index === 0), [state]);
  const set = useCallback((id: string, open: boolean) => setState((s) => ({ ...s, [id]: open })), []);
  const all = (open: boolean) => {
    setState(Object.fromEntries(order.current.map((id) => [id, open])));
    setVersion((v) => v + 1);
  };
  const value = useMemo(() => ({ register, isOpen, set, version }), [register, isOpen, set, version]);

  return (
    <GroupContext.Provider value={value}>
      <div className={cx("space-y-6", className)}>
        {toolbar && (
          <div className="-mb-2 flex justify-end gap-1 text-label">
            <button type="button" onClick={() => all(true)} className="press inline-flex items-center gap-1 rounded-lg px-2 py-1 font-medium text-muted hover:bg-surface-2 hover:text-ink">
              <ChevronsUpDown className="size-3.5" aria-hidden /> Expand all
            </button>
            <button type="button" onClick={() => all(false)} className="press inline-flex items-center gap-1 rounded-lg px-2 py-1 font-medium text-muted hover:bg-surface-2 hover:text-ink">
              <ChevronsDownUp className="size-3.5" aria-hidden /> Collapse all
            </button>
          </div>
        )}
        {children}
      </div>
    </GroupContext.Provider>
  );
}

/**
 * One foldable section. ``id`` must be stable for the page; ``summary`` is the line shown while
 * closed; ``chip`` sits on the right in both states.
 */
export function Section({
  id,
  title,
  summary,
  chip,
  icon,
  actions,
  children,
  tone,
  defaultOpen,
  tour,
  className,
}: {
  id: string;
  title: ReactNode;
  summary?: ReactNode;
  chip?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  tone?: "attention" | "primary";
  defaultOpen?: boolean;
  tour?: string;
  className?: string;
}) {
  const group = useContext(GroupContext);
  const index = group ? group.register(id) : 0;
  const [local, setLocal] = useState(defaultOpen ?? true);
  const open = group ? group.isOpen(id, defaultOpen === undefined ? index : defaultOpen ? 0 : 1) : local;
  const toggle = () => (group ? group.set(id, !open) : setLocal(!open));
  const bodyId = useId();

  return (
    <section
      data-tour={tour}
      className={cx(
        "card overflow-hidden",
        tone === "attention" && "border-attention-dot/40",
        tone === "primary" && "border-primary-line",
        className,
      )}
    >
      <div className={cx("flex items-center gap-3 px-6 py-4", tone === "attention" && open && "bg-attention-soft/60")}>
        <h2 className="min-w-0 flex-1">
        <button type="button" onClick={toggle} aria-expanded={open} aria-controls={bodyId} className="group flex w-full min-w-0 items-center gap-3 text-left">
          <ChevronDown aria-hidden className={cx("size-5 shrink-0 text-faint transition-transform duration-300 group-hover:text-ink", !open && "-rotate-90")} />
          {icon && <span className="shrink-0 text-primary">{icon}</span>}
          <span className="min-w-0">
            <span className="block text-heading font-semibold text-ink">{title}</span>
            {summary && <span className="block truncate text-small font-normal text-muted">{summary}</span>}
          </span>
        </button>
        </h2>
        {chip && <div className="hidden shrink-0 sm:block">{chip}</div>}
        {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div id={bodyId} className={cx("grid transition-[grid-template-rows] duration-300 ease-out", open ? "grid-rows-[1fr]" : "grid-rows-[0fr]")}>
        <div className="min-h-0 overflow-hidden">
          <div className={cx("border-t border-line px-6 py-6", open && "animate-fade")} hidden={!open}>
            {children}
          </div>
        </div>
      </div>
    </section>
  );
}
