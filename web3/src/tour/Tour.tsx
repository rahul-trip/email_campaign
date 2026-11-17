import { useQuery } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { client, ok } from "../api/client";
import { Button } from "../ui/compat";
import { SECTIONS, type Place } from "./steps";
import { Confetti } from "../pages/Onboarding";

const STORAGE_KEY = "outbound.tour";

/** Whether the person has been through the tour (or dismissed it). Storage may be blocked. */
export function tourSeen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "done";
  } catch {
    return true; // cannot remember, so never pop up on every visit
  }
}
function markSeen() {
  try {
    localStorage.setItem(STORAGE_KEY, "done");
  } catch {
    /* nothing to do: the tour can still be started by hand */
  }
}

const TourContext = createContext<{ start: () => void }>({ start: () => undefined });
export const useTour = () => useContext(TourContext);

type Position = { section: number; step: number };
type Box = { target: string; top: number; left: number; width: number; height: number };

const PAD = 6;
const TOTAL = SECTIONS.reduce((n, s) => n + s.steps.length, 0);
const CARD_WIDTH = 360;

/** The element a step points at: the first one on screen, since some appear twice (wide and narrow layouts). */
function findTarget(name: string): Element | null {
  const all = [...document.querySelectorAll(`[data-tour="${name}"]`)];
  return all.find((element) => {
    const r = element.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.right > 0 && r.left < window.innerWidth;
  }) ?? null;
}

export function TourProvider({ children, autoStart }: { children: ReactNode; autoStart: boolean }) {
  const [at, setAt] = useState<Position | null>(null);
  const [measured, setBox] = useState<Box | null>(null);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const active = at !== null;

  // The lead pages need a real lead to show; the newest one will do.
  const firstLead = useQuery({
    queryKey: ["tour-first-lead"],
    queryFn: () => ok(client.GET("/api/companies", { params: { query: { limit: 1 } } })),
    enabled: active,
  });
  const leadId = firstLead.data?.items[0]?.id;

  const start = useCallback(() => setAt({ section: 0, step: 0 }), []);
  const end = useCallback(() => {
    markSeen();
    setAt(null);
    setBox(null);
  }, []);

  useEffect(() => {
    if (autoStart && !tourSeen()) start();
  }, [autoStart, start]);

  const section = at ? SECTIONS[at.section] : null;
  const step = section && at ? section.steps[at.step] : null;
  // A measurement belongs to the step it was taken for; never show the last step's box on this one.
  const box = measured && measured.target === step?.target ? measured : null;

  // Go to the screen the current section is about, once when the section starts (and again if
  // the newest lead turns up late), so a person who clicks around is not pulled back.
  const sectionId = section?.id;
  useEffect(() => {
    if (section) void navigate({ to: destination(section.place, leadId) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionId, leadId]);

  // Point at the step's element. It may not exist yet (the page is loading, or there is no data),
  // so look again until it appears; if it never does, the card is centred.
  useEffect(() => {
    if (!step?.target) {
      setBox(null);
      return;
    }
    const wanted = step.target;
    let scrolled = false;
    const measure = () => {
      const element = findTarget(wanted);
      if (!element) return setBox(null);
      if (!scrolled) {
        element.scrollIntoView({ block: "center", behavior: "smooth" });
        scrolled = true;
      }
      const r = element.getBoundingClientRect();
      const next = { target: wanted, top: Math.round(r.top), left: Math.round(r.left), width: Math.round(r.width), height: Math.round(r.height) };
      // Only a real move repositions the card, so it never jitters on sub-pixel changes.
      setBox((prev) =>
        prev && prev.target === next.target && Math.abs(prev.top - next.top) < 2 && Math.abs(prev.left - next.left) < 2 && Math.abs(prev.width - next.width) < 2 && Math.abs(prev.height - next.height) < 2 ? prev : next,
      );
    };
    measure();
    const timer = window.setInterval(measure, 250);
    return () => window.clearInterval(timer);
  }, [step?.target, pathname]);

  // Moves read the latest position, so the keyboard listener never acts on a stale one.
  const next = useCallback(() => {
    setAt((prev) => {
      if (!prev) return prev;
      const here = SECTIONS[prev.section]!;
      if (prev.step + 1 < here.steps.length) return { section: prev.section, step: prev.step + 1 };
      if (prev.section + 1 < SECTIONS.length) return { section: prev.section + 1, step: 0 };
      markSeen();
      setBox(null);
      return null;
    });
  }, []);
  const back = useCallback(() => {
    setAt((prev) => {
      if (!prev) return prev;
      if (prev.step > 0) return { section: prev.section, step: prev.step - 1 };
      if (prev.section > 0) return { section: prev.section - 1, step: SECTIONS[prev.section - 1]!.steps.length - 1 };
      return prev;
    });
  }, []);

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") end();
      if ((event.target as HTMLElement).closest("input, textarea, select")) return;
      if (event.key === "ArrowRight") next();
      if (event.key === "ArrowLeft") back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, end, next, back]);

  const value = useMemo(() => ({ start }), [start]);
  const first = at ? at.section === 0 && at.step === 0 : false;
  const overall = at ? SECTIONS.slice(0, at.section).reduce((n, x) => n + x.steps.length, 0) + at.step + 1 : 0;
  const last = at && section ? at.section === SECTIONS.length - 1 && at.step === section.steps.length - 1 : false;

  return (
    <TourContext.Provider value={value}>
      {children}
      {at && section && step && (
        <>
          {/* Dims the page and rings the element; clicks pass through it. */}
          <div
            aria-hidden
            className="pointer-events-none fixed z-[60] rounded-lg transition-all duration-200"
            style={
              box
                ? { top: box.top - PAD, left: box.left - PAD, width: box.width + PAD * 2, height: box.height + PAD * 2, boxShadow: "0 0 0 9999px rgba(10,12,18,.55), 0 0 0 6px var(--primary-line), 0 0 32px 8px var(--primary-line)", outline: "2px solid var(--primary)", borderRadius: 14 }
                : { inset: 0, background: "rgba(10,12,18,.5)" }
            }
          />
          {last && <Confetti />}
          <div
            role="dialog"
            aria-label="Product tour"
            data-target-found={step.target ? String(box !== null) : "none"}
            className="fixed z-[70] flex animate-rise flex-col overflow-hidden rounded-2xl border border-line bg-surface p-5 shadow-3"
            style={cardPosition(box)}
          >
            <span aria-hidden className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-primary via-violet to-good-dot" />
            <div className="flex items-center justify-between gap-2 text-label font-semibold tracking-wide text-primary uppercase">
              <span>{section.title}</span>
              <span className="tnum text-muted normal-case">
                {overall} of {TOTAL}
              </span>
            </div>
            <div className="relative mt-3 h-6" aria-hidden>
              <div className="absolute inset-x-0 top-1/2 h-1 -translate-y-1/2 rounded-full bg-surface-3" />
              <div className="absolute top-1/2 left-0 h-1 -translate-y-1/2 rounded-full bg-gradient-to-r from-primary to-violet transition-all duration-500" style={{ width: `${((overall - 1) / Math.max(1, TOTAL - 1)) * 100}%` }} />
              {Array.from({ length: TOTAL }, (_, i) => (
                <span key={i} className={`absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full ${i < overall ? "bg-primary" : "bg-surface-3 ring-2 ring-surface"}`} style={{ left: `${(i / Math.max(1, TOTAL - 1)) * 100}%` }} />
              ))}
              <span className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2 text-[18px] transition-all duration-500 [transition-timing-function:cubic-bezier(0.2,0.9,0.3,1.4)]" style={{ left: `${((overall - 1) / Math.max(1, TOTAL - 1)) * 100}%` }}>
                🚀
              </span>
            </div>
            <div className="min-h-0 overflow-y-auto">
            <div key={step.title} className="mt-3 flex animate-rise items-start gap-3">
              {step.icon && <span className="flex size-12 shrink-0 animate-pop items-center justify-center rounded-2xl bg-gradient-to-br from-primary-soft to-surface-3 text-[26px] shadow-1">{step.icon}</span>}
              <h2 className="pt-1 text-title font-semibold text-ink">{step.title}</h2>
            </div>
            <p className="mt-1.5 text-body text-ink-2">{step.body}</p>
            {leadNeeded(section.place) && firstLead.isSuccess && !leadId && (
              <p className="mt-2 rounded-lg bg-attention-soft p-2 text-small text-attention">There is no lead yet, so there is nothing to point at. Add a lead and start a run, then take the tour again.</p>
            )}
            {step.target && !box && !(leadNeeded(section.place) && firstLead.isSuccess && !leadId) && (
              <p className="mt-2 text-label text-muted">This part of the screen appears once there is something to show.</p>
            )}
            </div>
            <div className="mt-4 flex shrink-0 flex-wrap items-center gap-2">
              <Button autoFocus onClick={next}>
                {last ? "Let's go" : first ? "Show me" : "Next"}
              </Button>
              {!first && (
                <Button variant="secondary" onClick={back}>
                  Back
                </Button>
              )}
              <Button variant="ghost" onClick={end} className="ml-auto">
                {last ? "Close" : "Skip tour"}
              </Button>
            </div>
          </div>
        </>
      )}
    </TourContext.Provider>
  );
}

const leadNeeded = (place: Place) => place === "lead" || place === "journey";

function destination(place: Place, leadId: string | undefined): string {
  if (place === "lead") return leadId ? `/leads/${leadId}` : "/leads";
  if (place === "journey") return leadId ? `/leads/${leadId}?tab=journey` : "/leads";
  return place;
}

// Room the card needs: the longest step's text with its buttons.
const CARD_ROOM = 340;

/** Below the element if it fits, else above it, else bottom-right; centred when nothing is pointed at. */
function cardPosition(box: Box | null): CSSProperties {
  const width = Math.min(CARD_WIDTH, window.innerWidth - 16);
  const fit = (room: number) => ({ maxHeight: Math.max(220, room) });
  if (!box) return { width, top: "50%", left: "50%", transform: "translate(-50%, -50%)", ...fit(window.innerHeight - 32) };
  const left = Math.min(Math.max(8, box.left), window.innerWidth - width - 8);
  const below = box.top + box.height + PAD + 12;
  if (window.innerHeight - below >= CARD_ROOM) return { width, top: below, left, ...fit(window.innerHeight - below - 16) };
  if (box.top - PAD - 12 >= CARD_ROOM) return { width, bottom: window.innerHeight - box.top + PAD + 12, left, ...fit(box.top - PAD - 28) };
  return { width, bottom: 16, right: 16, ...fit(window.innerHeight - 32) };
}
