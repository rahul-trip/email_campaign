import { useQuery } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { client, ok } from "../api/client";
import { Button } from "../components/ui";
import { SECTIONS, type Place } from "./steps";

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
      setBox({ target: wanted, top: r.top, left: r.left, width: r.width, height: r.height });
    };
    measure();
    const timer = window.setInterval(measure, 250);
    return () => window.clearInterval(timer);
  }, [step?.target, pathname]);

  const next = () => {
    if (!at || !section) return;
    if (at.step + 1 < section.steps.length) setAt({ section: at.section, step: at.step + 1 });
    else skipSection();
  };
  const back = () => {
    if (!at) return;
    if (at.step > 0) setAt({ section: at.section, step: at.step - 1 });
    else if (at.section > 0) setAt({ section: at.section - 1, step: SECTIONS[at.section - 1].steps.length - 1 });
  };
  const skipSection = () => {
    if (!at) return;
    if (at.section + 1 < SECTIONS.length) setAt({ section: at.section + 1, step: 0 });
    else end();
  };

  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && end();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active, end]);

  const value = useMemo(() => ({ start }), [start]);
  const first = at ? at.section === 0 && at.step === 0 : false;
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
                ? { top: box.top - PAD, left: box.left - PAD, width: box.width + PAD * 2, height: box.height + PAD * 2, boxShadow: "0 0 0 9999px rgba(10,12,18,.5)", outline: "2px solid var(--primary-container)" }
                : { inset: 0, background: "rgba(10,12,18,.5)" }
            }
          />
          <div
            role="dialog"
            aria-label="Product tour"
            data-target-found={step.target ? String(box !== null) : "none"}
            className="fixed z-[70] rounded-xl border border-line bg-surface p-4 shadow-2xl"
            style={cardPosition(box)}
          >
            <div className="flex items-center justify-between gap-2 text-[11px] text-muted">
              <span>
                {section.title} · section {at.section + 1} of {SECTIONS.length} · step {at.step + 1} of {section.steps.length}
              </span>
            </div>
            <div className="mt-2 flex gap-1" aria-hidden>
              {SECTIONS.map((s, i) => (
                <span key={s.id} className={`h-1 flex-1 rounded-full ${i < at.section ? "bg-primary-container" : i === at.section ? "bg-primary-container/60" : "bg-surface-container"}`} />
              ))}
            </div>
            <h2 className="mt-3 text-[15px] font-semibold">{step.title}</h2>
            <p className="mt-1 text-[13px] leading-relaxed text-ink">{step.body}</p>
            {leadNeeded(section.place) && firstLead.isSuccess && !leadId && (
              <p className="mt-2 rounded-lg bg-attention-container p-2 text-xs text-on-attention-container">There is no lead yet, so there is nothing to point at. Add a target and start a run, then take the tour again.</p>
            )}
            {step.target && !box && !(leadNeeded(section.place) && firstLead.isSuccess && !leadId) && (
              <p className="mt-2 text-[11px] text-muted">This part of the screen appears once there is something to show.</p>
            )}
            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button autoFocus onClick={next}>
                {last ? "Finish" : "Next"}
              </Button>
              {!first && (
                <Button variant="secondary" onClick={back}>
                  Back
                </Button>
              )}
              <Button variant="secondary" onClick={skipSection}>
                Skip section
              </Button>
              <Button variant="ghost" onClick={end} className="ml-auto">
                End tour
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
  if (place === "journey") return leadId ? `/leads/${leadId}/journey` : "/leads";
  return place;
}

// Room the card needs: the longest step's text with its buttons.
const CARD_ROOM = 340;

/** Below the element if it fits, else above it, else bottom-right; centred when nothing is pointed at. */
function cardPosition(box: Box | null): CSSProperties {
  const width = Math.min(CARD_WIDTH, window.innerWidth - 16);
  if (!box) return { width, top: "50%", left: "50%", transform: "translate(-50%, -50%)" };
  const left = Math.min(Math.max(8, box.left), window.innerWidth - width - 8);
  const below = box.top + box.height + PAD + 12;
  if (window.innerHeight - below >= CARD_ROOM) return { width, top: below, left };
  if (box.top - PAD - 12 >= CARD_ROOM) return { width, bottom: window.innerHeight - box.top + PAD + 12, left };
  return { width, bottom: 16, right: 16 };
}
