/**
 * The guided tour: one place to edit when a screen or feature changes.
 *
 * Add a section when you add a screen, add a step when you add something worth pointing at, and
 * give the element `data-tour="name"` (or `tour="name"` on a Card or Tabs) matching `target` here.
 * The tour test in e2e/tour.spec.ts fails if a step points at something that no longer exists.
 * Also update the "Guided tour" part of docs/USER_MANUAL.md.
 */

/** Where a section lives. The two lead pages need a real lead, so the tour opens the newest one. */
export type Place = "/" | "/onboarding" | "/targets" | "/runs" | "/review" | "/attention" | "/leads" | "/reports" | "/settings" | "/compliance" | "lead" | "journey";

export type Step = {
  /** The `data-tour` name of the element to point at; none means a centred message. */
  target?: string;
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
      {
        title: "Welcome to Outbound",
        body: "This short tour shows each screen. Move on with Next, jump to the next screen with Skip section, or end it at any time. Start it again from Tour at the top right.",
      },
      {
        target: "nav",
        title: "The main menu",
        body: "Work is what waits for you: emails to review and leads that need a decision. Pipeline is where companies go in and the engine runs. Items marked Soon arrive in later phases.",
      },
      {
        target: "workspace-switcher",
        title: "Your workspace",
        body: "Everything you see belongs to this workspace. If you work in several, switch here; the address bar always shows which one you are in, so a link you share opens the right one.",
      },
      {
        target: "user-menu",
        title: "Your account",
        body: "Change your password, sign out other devices, or sign out.",
      },
      {
        target: "search",
        title: "Find any lead",
        body: "Type a company or domain and press Enter. Ctrl+K (Cmd+K on a Mac) jumps here from anywhere.",
      },
      {
        target: "needs-you",
        title: "What needs you",
        body: "Emails to review, leads on hold, failures and websites to confirm. Each card opens the list behind it. When everything shows 0, nothing is waiting on you.",
      },
      {
        target: "pipeline",
        title: "The pipeline",
        body: "How many companies sit at each of the eight stages, and how many left the main path. Click a stage to see its leads.",
      },
    ],
  },
  {
    id: "targets",
    title: "Add leads",
    place: "/targets",
    steps: [
      {
        target: "add-target",
        title: "Add a company",
        body: "One detail is enough: a website, a company name, a work email or a LinkedIn profile. What you type is marked as yours and never overwritten. Tick Check only to see what would happen first.",
      },
      {
        target: "target-tabs",
        title: "Upload a list, confirm websites",
        body: "Upload a CSV or Excel file: preview it first, nothing is saved until you import. When a company name could mean more than one website, it waits under Websites to confirm.",
      },
    ],
  },
  {
    id: "runs",
    title: "Runs",
    place: "/runs",
    steps: [
      {
        target: "start-run",
        title: "Start the engine",
        body: "A run researches each company, finds and checks an email address, and writes the email. Discovery also searches for new companies. The worker process does the work, so you can leave the page.",
      },
      {
        target: "recent-runs",
        title: "Watch it work",
        body: "Progress and spend update while a run is going. Cancel stops it between companies. If a run stays queued, the worker is not running. Open a run to see every lead it moved on, held, failed or will retry, with each step; click a lead to go to it.",
      },
    ],
  },
  {
    id: "review",
    title: "Review",
    place: "/review",
    steps: [
      {
        target: "review-queue",
        title: "Emails waiting for you",
        body: "Every email the engine writes waits here. Nothing reaches your mailbox until you approve it. J and K move through the queue.",
      },
      {
        target: "review-editor",
        title: "Read, edit, approve",
        body: "The email exactly as it will be drafted, footer included. Edit it if you like: your changes are shown and kept, and the writer learns from them. If it relies on a check you skipped, tick that you know before Approve works. Approve makes a draft on the next run; Write it again throws this one away and the next run writes a fresh one; Reject needs a reason.",
      },
      {
        target: "review-opening",
        title: "What it opens with",
        body: "The dated news item the email starts from, linked to its source, so you can check it is real and right before approving. Without recent news it opens with a fact from their own site.",
      },
      {
        target: "review-checks",
        title: "Why this lead, and the checks",
        body: "The research behind the email, your notes, and every quality check with the country rule that applies. Read any flag before approving.",
      },
    ],
  },
  {
    id: "attention",
    title: "Needs attention",
    place: "/attention",
    steps: [
      {
        target: "attention-filter",
        title: "Holds, failures, websites",
        body: "Everything that waits on a decision other than review. Each group says why in plain words and offers the action that fixes it, such as adding a person who has given consent.",
      },
    ],
  },
  {
    id: "leads",
    title: "Leads",
    place: "/leads",
    steps: [
      {
        target: "leads-list",
        title: "Every company",
        body: "Search and filter by status or hold reason. The filters are part of the address, so a filtered view can be bookmarked. The stage bar shows how far each lead has come.",
      },
      {
        target: "leads-journey",
        title: "Open a lead's journey",
        body: "Journey opens the story of one company. The next section shows it.",
      },
    ],
  },
  {
    id: "journey",
    title: "A lead's journey",
    place: "journey",
    steps: [
      {
        target: "journey-header",
        title: "Where this lead is",
        body: "Its state and what happens next, including whether the next move is yours.",
      },
      {
        target: "journey-stages",
        title: "The eight stages",
        body: "Green is done, blue is next for the engine, amber is held or waiting for you, red is failed or stopped. Click a stage, or use the arrow keys, to read it.",
      },
      {
        target: "journey-stage",
        title: "What happened at a stage",
        body: "The details found, any holds or failures, and every vendor call made with its cost. Where a country rule held the lead, you can skip the rule for it from this stage.",
      },
      {
        target: "journey-origin",
        title: "How it arrived",
        body: "Typed in, imported from a file, sent by the webhook or found by search: who added it, when, and exactly what was supplied.",
      },
    ],
  },
  {
    id: "lead",
    title: "Acting on a lead",
    place: "lead",
    steps: [
      {
        target: "lead-header",
        title: "Status and next actions",
        body: "A failed lead can be retried. A held lead explains why and offers the fix. A disqualified lead can be overridden unless a country rule blocks it. Research again reads the site and the news afresh and rewrites the email (a waiting email is cancelled). An email waiting for review has Open in Review, under Emails.",
      },
      {
        target: "lead-people",
        title: "People and consent",
        body: "Each person with their addresses, where each came from and who checked it, and who the email is to. Someone you gave an address or consent to is always first. Edit a name or give a new address, record consent, write to someone else instead, remove a wrong match, or suppress a person for good.",
      },
      {
        target: "lead-add-person",
        title: "Add a person",
        body: "Someone you know at the company, with a first and last name or their work email. Tick that they have consented and say where it came from, and a lead held for consent is released and carries on.",
      },
      {
        target: "lead-research",
        title: "What research found",
        body: "What the company does, how well it fits, your research questions' answers, and recent dated news about the company and its market, each a link to its source. The email opens with one of them when there is one.",
      },
      {
        target: "lead-policy",
        title: "Country rule",
        body: "Skip the country's rule for this lead from a step onward, with a reason that is kept. A lead it held goes straight on. The do-not-contact list still applies, and approving the email asks you to confirm.",
      },
      {
        target: "lead-edit",
        title: "Edit a lead",
        body: "Change the name, country, priority or campaign. What you set is marked as yours and kept.",
      },
      {
        target: "lead-danger",
        title: "Suppress or delete",
        body: "Suppress stops all contact with the domain. Delete removes the lead for good: you type its domain to confirm, and a lead that has been emailed cannot be deleted.",
      },
    ],
  },
  {
    id: "reports",
    title: "Reports",
    place: "/reports",
    steps: [
      {
        target: "reports-quality",
        title: "Is it working?",
        body: "The share of first emails sent without an edit (the target is 8 of 10), how many were flagged, and spend per prospect against the budget.",
      },
    ],
  },
  {
    id: "settings",
    title: "Settings",
    place: "/settings",
    steps: [
      {
        target: "settings-tabs",
        title: "Setup, profile, mailboxes, limits, team",
        body: "The setup check lists what is missing. The sender profile is who you are in every email. Mailboxes is where you connect Microsoft 365, Google or any IMAP mailbox: approved emails are saved as drafts there. Limits hold the budget per prospect, the email length and the footer switch. Under Sender profile, How you write sets the greeting, what you want from the emails and past emails of yours to learn your voice from. Team is who works here: admins invite people and set their roles. Integrations holds the signed address other systems use to add targets. Plan and usage shows your allowances, what is used, when they renew, and lets you ask for more credits. Your account changes your password.",
      },
      {
        target: "setup-check",
        title: "Confirm your sender profile",
        body: "Every statement in the profile ends up in emails under your name. Read it, keep only what is true, and press Confirm and save: no email is written until you do.",
      },
    ],
  },
  {
    id: "onboarding",
    title: "Setting up",
    place: "/onboarding",
    steps: [
      {
        target: "onboarding-steps",
        title: "Four steps to your first email",
        body: "A new workspace starts empty. Your company (what you may truthfully say, and who signs), a mailbox for the drafts, who you want to reach, and your first leads. A tick appears as soon as a step is done, wherever you did it; the Dashboard shows Get started until the essentials are in place.",
      },
    ],
  },
  {
    id: "compliance",
    title: "Policies and privacy",
    place: "/compliance",
    steps: [
      {
        target: "compliance-tabs",
        title: "Rules and requests",
        body: "The rule and footer for each country, the do-not-contact list, and Forget a person for erasure requests. Have the country rules reviewed and record who did.",
      },
      {
        target: "compliance-switch",
        title: "Switch country rules on or off",
        body: "Off means no lead is held or blocked because of its country, for the whole workspace; a red banner says so on every page. Suppression still applies. Add any country with any rule below, or remove one.",
      },
    ],
  },
];
