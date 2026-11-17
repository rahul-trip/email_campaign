/** Things that float: dialogs, the slide-over drawer, menus, toasts and tabs. */
import { CheckCircle2, Info, X, XCircle } from "lucide-react";
import { createContext, useCallback, useContext, useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { cx } from "../lib/cx";
import { Button } from "./core";

function useEscape(onClose: () => void) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
}

/** Keeps keyboard focus inside an overlay and gives it back when it closes. */
function useFocusTrap<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const first = node?.querySelector<HTMLElement>("[autofocus], input, textarea, select, button:not([data-close])");
    (first ?? node)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !node) return;
      const items = [...node.querySelectorAll<HTMLElement>('a[href], button:not([disabled]), input, textarea, select, [tabindex]:not([tabindex="-1"])')];
      if (!items.length) return;
      const [head, tail] = [items[0]!, items[items.length - 1]!];
      if (e.shiftKey && document.activeElement === head) {
        e.preventDefault();
        tail.focus();
      } else if (!e.shiftKey && document.activeElement === tail) {
        e.preventDefault();
        head.focus();
      }
    };
    node?.addEventListener("keydown", onKey);
    return () => {
      node?.removeEventListener("keydown", onKey);
      before?.focus?.();
    };
  }, []);
  return ref;
}

export function Dialog({ title, children, onClose, footer, wide }: { title: ReactNode; children: ReactNode; onClose: () => void; footer?: ReactNode; wide?: boolean }) {
  useEscape(onClose);
  const ref = useFocusTrap<HTMLDivElement>();
  const labelId = useId();
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center p-4 sm:items-center">
      <div className="absolute inset-0 animate-fade bg-[var(--scrim)] backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={labelId} tabIndex={-1} className={cx("relative w-full animate-rise rounded-2xl border border-line bg-surface shadow-3", wide ? "max-w-2xl" : "max-w-lg")}>
        <div className="flex items-start justify-between gap-4 px-6 pt-5">
          <h2 id={labelId} className="text-heading font-semibold text-ink">
            {title}
          </h2>
          <button type="button" data-close onClick={onClose} aria-label="Close" className="press -mr-2 rounded-lg p-1.5 text-faint hover:bg-surface-2 hover:text-ink">
            <X className="size-5" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-y-auto px-6 py-4">{children}</div>
        {footer && <div className="flex flex-wrap justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** A right-hand slide-over: the page stays visible, dimmed, behind it. */
export function Drawer({ title, subtitle, children, onClose, footer, width = 480 }: { title: ReactNode; subtitle?: ReactNode; children: ReactNode; onClose: () => void; footer?: ReactNode; width?: number }) {
  useEscape(onClose);
  const ref = useFocusTrap<HTMLDivElement>();
  const labelId = useId();
  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 animate-fade bg-[var(--scrim)] backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-labelledby={labelId}
        tabIndex={-1}
        style={{ maxWidth: width }}
        className="absolute inset-y-0 right-0 flex w-full flex-col rounded-l-2xl border-l border-line bg-surface shadow-3 [animation:drawer-in_0.36s_cubic-bezier(0.2,0.9,0.3,1.05)_both]"
      >
        <div className="flex items-start justify-between gap-4 border-b border-line px-6 py-5">
          <div>
            <h2 id={labelId} className="text-title font-semibold text-ink">
              {title}
            </h2>
            {subtitle && <p className="mt-0.5 text-body text-muted">{subtitle}</p>}
          </div>
          <button type="button" data-close onClick={onClose} aria-label="Close" className="press -mr-2 rounded-lg p-1.5 text-faint hover:bg-surface-2 hover:text-ink">
            <X className="size-5" />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
        {footer && <div className="border-t border-line px-6 py-4">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

/** Asks before something that cannot be undone. */
export function Confirm({
  title,
  children,
  confirm,
  onConfirm,
  onClose,
  busy,
  danger,
}: {
  title: ReactNode;
  children: ReactNode;
  confirm: string;
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
  danger?: boolean;
}) {
  return (
    <Dialog
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant={danger ? "danger" : "primary"} busy={busy} onClick={onConfirm}>
            {confirm}
          </Button>
        </>
      }
    >
      <div className="text-body text-ink-2">{children}</div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ menu

export type MenuItem = { label: ReactNode; onSelect: () => void; hint?: ReactNode; tone?: "danger"; current?: boolean };

export function Menu({ label, button, items, header, align = "right", buttonClassName }: { label: string; button: ReactNode; items: MenuItem[]; header?: ReactNode; align?: "left" | "right"; buttonClassName?: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <div ref={box} className="relative">
      <button type="button" aria-label={label} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)} className={buttonClassName}>
        {button}
      </button>
      {open && (
        <div role="menu" className={cx("glass absolute z-40 mt-2 min-w-56 animate-rise rounded-xl border border-line p-1.5 shadow-3", align === "right" ? "right-0" : "left-0")}>
          {header && <div className="border-b border-line px-3 pt-1.5 pb-2.5">{header}</div>}
          {items.map((item, i) => (
            <button
              key={i}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={cx("flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-body hover:bg-surface-2", item.tone === "danger" ? "text-error" : "text-ink", item.current && "font-semibold")}
            >
              <span>{item.label}</span>
              {item.hint && <span className="text-small text-faint">{item.hint}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ toasts

type Toast = { id: number; tone: "good" | "error" | "info"; title: ReactNode; body?: ReactNode; action?: { label: string; onClick: () => void } };
const ToastContext = createContext<(toast: Omit<Toast, "id">) => void>(() => {});
export const useToast = () => useContext(ToastContext);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((toast: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((all) => [...all.slice(-2), { ...toast, id }]);
    window.setTimeout(() => setToasts((all) => all.filter((t) => t.id !== id)), 6000);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className="glass pointer-events-auto flex animate-rise gap-3 rounded-xl border border-line px-4 py-3 shadow-3">
            {t.tone === "good" ? <CheckCircle2 className="mt-0.5 size-5 shrink-0 text-good" /> : t.tone === "error" ? <XCircle className="mt-0.5 size-5 shrink-0 text-error" /> : <Info className="mt-0.5 size-5 shrink-0 text-primary" />}
            <div className="min-w-0 flex-1">
              <div className="text-body font-semibold text-ink">{t.title}</div>
              {t.body && <div className="text-small text-muted">{t.body}</div>}
              {t.action && (
                <button type="button" onClick={t.action.onClick} className="mt-1 text-small font-semibold text-primary hover:underline">
                  {t.action.label}
                </button>
              )}
            </div>
            <button type="button" aria-label="Dismiss" onClick={() => setToasts((all) => all.filter((x) => x.id !== t.id))} className="self-start text-faint hover:text-ink">
              <X className="size-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// ------------------------------------------------------------------ tabs

export function Tabs<T extends string>({ value, onChange, tabs, label, tour }: { value: T; onChange: (value: T) => void; tabs: readonly { key: T; label: ReactNode; count?: number }[]; label: string; tour?: string }) {
  return (
    <div role="tablist" aria-label={label} data-tour={tour} className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          role="tab"
          aria-selected={value === tab.key}
          onClick={() => onChange(tab.key)}
          className={cx(
            "relative -mb-px inline-flex items-center gap-2 border-b-2 px-3 py-2.5 text-body font-semibold whitespace-nowrap transition-colors",
            value === tab.key ? "border-primary text-ink" : "border-transparent text-muted hover:text-ink",
          )}
        >
          {tab.label}
          {tab.count !== undefined && <span className={cx("tnum rounded-full px-1.5 text-label", value === tab.key ? "bg-primary-soft text-primary" : "bg-surface-3 text-muted")}>{tab.count}</span>}
        </button>
      ))}
    </div>
  );
}
