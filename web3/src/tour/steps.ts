/**
 * The guided tour: one place to edit when a screen or feature changes.
 *
 * Add a section when you add a screen, add a step when you add something worth pointing at, and
 * give the element `data-tour="name"` (or `tour="name"` on a Card or Tabs) matching `target` here.
 * The tour test in e2e/tour.spec.ts fails if a step points at something that no longer exists.
 * Also update the "Guided tour" part of docs/USER_MANUAL.md.
 */

/** Where a section lives. The two lead pages need a real lead, so the tour opens the newest one. */
export type Place = "/" | "/onboarding" | "/targets" | "/campaigns" | "/runs" | "/review" | "/attention" | "/linkedin" | "/leads" | "/reports" | "/settings" | "/compliance" | "lead" | "journey";

export type Step = {
  /** The `data-tour` name of the element to point at; none means a centred message. */
  target?: string;
  /** A big emoji for the card's badge. */
  icon?: string;
  title: string;
  body: string;
};

export type Section = {
  id: string;
  title: string;
  place: Place;
  steps: Step[];
};

export const SECTIONS: Section[] = [
  {
    id: "welcome",
    title: "Welcome",
    place: "/",
    steps: [
      { icon: "👋", title: "Welcome to Outbound", body: "Seven quick stops, about a minute. See how the engine finds, researches and writes for you, and where you stay in charge." },
      { target: "today-hero", icon: "☀️", title: "Your day starts here", body: "The emails ready to approve come first, with the best three right here and one button to start reviewing. Hot leads to message on LinkedIn follow; what the engine screened out stays quiet below." },
      { target: "search", icon: "⌨️", title: "⌘K finds anything", body: "Press ⌘K (Ctrl+K) anywhere to open a lead or jump to any page." },
    ],
  },
  {
    id: "review",
    title: "Emails ready",
    place: "/review",
    steps: [{ target: "review-queue", icon: "✍️", title: "Approve in one keystroke", body: "Every email waits here, hot leads first. Edit it, ask for changes, or press Ctrl+Enter. Nothing is sent until you approve." }],
  },
  {
    id: "attention",
    title: "Failed leads",
    place: "/attention",
    steps: [{ target: "attention-filter", icon: "🧲", title: "Unstick leads in one click", body: "Only what you can unblock lands here: holds and steps that broke on every try. Each says why in plain words and has the fix. Companies that do not fit are screened out quietly." }],
  },
  {
    id: "leads",
    title: "Leads",
    place: "/leads",
    steps: [{ target: "leads-list", icon: "🗂️", title: "Every company, your way", body: "Saved views, fit and source filters, and each lead's contact and the AI credits it used. Open one to see its journey." }],
  },
  {
    id: "runs",
    title: "Discovery",
    place: "/runs",
    steps: [{ target: "start-run", icon: "🚀", title: "Start the engine", body: "Discovery already runs about four times a day. Start one now to watch what it finds." }],
  },
  {
    id: "campaigns",
    title: "Campaigns",
    place: "/campaigns",
    steps: [{ target: "campaign-brief", icon: "🎯", title: "Tell it who to look for", body: "Your brief decides which companies discovery keeps and how each lead is scored. A sharper brief means better leads." }],
  },
  {
    id: "done",
    title: "Ready",
    place: "/",
    steps: [{ icon: "🎉", title: "You're all set", body: "Reports, policies and settings are in the menu when you need them. Replay this tour any time from your account menu." }],
  },
];
