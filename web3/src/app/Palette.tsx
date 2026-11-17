/**
 * ⌘K / Ctrl+K from anywhere: jump to a page, run a common action, or find a lead by name or
 * website as you type. Arrow keys move, Enter opens, Escape closes.
 */
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { ArrowRight, CornerDownLeft, Moon, Plus, Radar, Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { client, ok } from "../api/client";
import { cx } from "../lib/cx";
import { describe, leadStatus } from "../lib/status";
import { useTheme } from "../lib/theme";
import { Avatar, Kbd } from "../ui/core";
import { NAV } from "./nav";
import { THEME_NEXT } from "./Shell";

export function useCommandPalette() {
  const [isOpen, setOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return { isOpen, open: () => setOpen(true), close: () => setOpen(false) };
}

type Item = { key: string; group: string; label: ReactNode; hint?: ReactNode; icon: ReactNode; run: () => void };

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [index, setIndex] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const [theme, setTheme] = useTheme();
  const q = text.trim();

  const leads = useQuery({
    queryKey: ["palette-leads", q],
    queryFn: () => ok(client.GET("/api/companies", { params: { query: { q, limit: 6 } } })),
    enabled: q.length >= 2,
    staleTime: 10_000,
  });

  const items = useMemo<Item[]>(() => {
    const go = (to: string, search?: Record<string, string>) => () => {
      onClose();
      void navigate({ to, search } as never);
    };
    const pages: Item[] = NAV.flatMap((g) =>
      g.items.map((i) => {
        const Icon = i.icon;
        return { key: `page:${i.to}`, group: "Go to", label: i.label, icon: <Icon className="size-4" />, run: go(i.to) };
      }),
    );
    const actions: Item[] = [
      { key: "add", group: "Actions", label: "Add a company or upload a list", icon: <Plus className="size-4" />, run: go("/targets") },
      { key: "run", group: "Actions", label: "Start a discovery run", icon: <Radar className="size-4" />, run: go("/runs") },
      { key: "theme", group: "Actions", label: `Switch theme (now ${theme})`, icon: <Moon className="size-4" />, run: () => setTheme(THEME_NEXT[theme]) },
    ];
    const found: Item[] = (leads.data?.items ?? []).map((c) => ({
      key: `lead:${c.id}`,
      group: "Leads",
      label: c.name || c.domain,
      hint: describe(leadStatus, c.status).label,
      icon: <Avatar name={c.name || c.domain} className="size-6 rounded-md text-[0.625rem]" />,
      run: go(`/leads/${c.id}`),
    }));
    const search: Item[] = q ? [{ key: "search", group: "Leads", label: `Show every lead matching “${q}”`, icon: <Search className="size-4" />, run: go("/leads", { q }) }] : [];
    const match = (item: Item) => !q || String(item.label).toLowerCase().includes(q.toLowerCase());
    return [...found, ...search, ...pages.filter(match), ...actions.filter(match)];
  }, [leads.data, q, navigate, onClose, theme, setTheme]);

  useEffect(() => setIndex(0), [q]);
  useEffect(() => input.current?.focus(), []);

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") onClose();
    else if (e.key === "ArrowDown") {
      e.preventDefault();
      setIndex((i) => Math.min(items.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setIndex((i) => Math.max(0, i - 1));
    } else if (e.key === "Enter") items[index]?.run();
  };

  let lastGroup = "";
  return createPortal(
    <div className="fixed inset-0 z-[55] flex items-start justify-center px-4 pt-[12vh]" onKeyDown={onKey}>
      <div className="absolute inset-0 animate-fade bg-[var(--scrim)] backdrop-blur-[3px]" onClick={onClose} aria-hidden />
      <div role="dialog" aria-modal="true" aria-label="Search and jump" className="glass relative w-full max-w-xl animate-rise overflow-hidden rounded-2xl border border-line shadow-3">
        <div className="flex items-center gap-3 border-b border-line px-4">
          <Search className="size-5 text-faint" aria-hidden />
          <input
            ref={input}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Find a lead, open a page, or run an action…"
            aria-label="Search"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-list"
            aria-activedescendant={items[index]?.key}
            className="h-14 flex-1 bg-transparent text-[1rem] text-ink outline-none placeholder:text-faint"
          />
          <Kbd>Esc</Kbd>
        </div>
        <ul id="palette-list" role="listbox" className="max-h-[52vh] overflow-y-auto p-2">
          {items.length === 0 && <li className="px-3 py-8 text-center text-body text-muted">{leads.isFetching ? "Searching…" : "Nothing matches."}</li>}
          {items.map((item, i) => {
            const header = item.group !== lastGroup ? item.group : null;
            lastGroup = item.group;
            return (
              <li key={item.key} id={item.key} role="option" aria-selected={i === index}>
                {header && <div className="px-3 pt-2 pb-1 text-label font-semibold tracking-wide text-faint uppercase">{header}</div>}
                <button
                  type="button"
                  onMouseEnter={() => setIndex(i)}
                  onClick={item.run}
                  className={cx("flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-body", i === index ? "bg-primary-soft text-ink" : "text-ink-2")}
                >
                  <span className={cx("flex size-7 items-center justify-center rounded-lg", i === index ? "text-primary" : "text-muted")}>{item.icon}</span>
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  {item.hint && <span className="text-small text-muted">{item.hint}</span>}
                  {i === index ? <CornerDownLeft className="size-4 text-primary" aria-hidden /> : <ArrowRight className="size-4 text-faint opacity-0" aria-hidden />}
                </button>
              </li>
            );
          })}
        </ul>
        <div className="flex gap-4 border-t border-line px-4 py-2 text-label text-muted">
          <span>
            <Kbd>↑</Kbd> <Kbd>↓</Kbd> move
          </span>
          <span>
            <Kbd>↵</Kbd> open
          </span>
        </div>
      </div>
    </div>,
    document.body,
  );
}
