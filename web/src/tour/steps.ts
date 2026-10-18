/**
 * The guided tour: one place to edit when a screen or feature changes.
 *
 * Add a section when you add a screen, add a step when you add something worth pointing at, and
 * give the element a `tour="name"` prop (or `data-tour="name"`) that matches `target` here.
 * The tour test in e2e/tour.spec.ts fails if a step points at something that no longer exists.
 * Also update the "Guided tour" part of docs/USER_MANUAL.md.
 */

/** Where a section lives. The two lead pages need a real lead, so the tour opens the newest one. */
export type Place = "/" | "/targets" | "/runs" | "/leads" | "/settings" | "lead" | "journey";

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
        body: "This short tour shows each screen. You can move on, skip the section you are in, or end the tour at any time. Start it again from the Tour button at the top.",
      },
      {
        target: "nav",
        title: "The main menu",
        body: "Review is where you approve emails. Targets is where companies go in. Leads lists every company. Runs starts the engine. Settings holds your sender profile and rules.",
      },
    ],
  },
  {
    id: "targets",
    title: "Targets",
    place: "/targets",
    steps: [
      {
        target: "add-target",
        title: "Add a company",
        body: "Type a website, a company name, a person or an email. Anything you type here is treated as yours and the engine will not overwrite it. Tick Check only, do not save to see what would happen first.",
      },
      {
        target: "upload-targets",
        title: "Upload a list",
        body: "Upload a CSV or Excel file. Preview it first: nothing is saved until you choose Import after preview.",
      },
      {
        target: "waiting-targets",
        title: "Rows that need you",
        body: "When the engine is not sure which website a company name means, the row waits here for you to confirm it.",
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
        body: "A run researches each company, finds and checks an email address, and writes the email. Discovery also searches for new companies. Runs are done by the worker process, so you can leave the page.",
      },
      {
        target: "recent-runs",
        title: "Watch it work",
        body: "Progress and spend update here while a run is going. You can cancel a run that is queued or running.",
      },
    ],
  },
  {
    id: "review",
    title: "Review",
    place: "/",
    steps: [
      {
        target: "review-queue",
        title: "Emails waiting for you",
        body: "Every email the engine writes waits here. Nothing is placed in your mailbox until you approve it.",
      },
      {
        target: "review-editor",
        title: "Read, edit, approve",
        body: "Edit the text if you like. Your edit is kept and shown next to the original, and the engine learns from it. Approve places a draft in your mailbox; Reject says why you did not like it.",
      },
      {
        target: "review-checks",
        title: "Checks and reasons",
        body: "The quality checks, the research behind the email and the country rule that applies. Read the flags before approving.",
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
        body: "Search by name or domain and filter by status or hold reason. A held, failed or disqualified lead says why it stopped.",
      },
      {
        target: "leads-journey",
        title: "Open a lead's journey",
        body: "The Journey link opens a dashboard for one company. The next section shows it.",
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
        body: "Its state, what happens next (and whether the next move is yours), how much it has cost and how many people and emails it has.",
      },
      {
        target: "journey-stages",
        title: "The eight stages",
        body: "Green is done, blue is next for the engine, amber is held or waiting for you, red is failed or stopped. Click a stage, or use the arrow keys, to read it.",
      },
      {
        target: "journey-stage",
        title: "What happened at a stage",
        body: "The details found, any holds or failures, and every vendor call made with its cost.",
      },
      {
        target: "journey-origin",
        title: "How it arrived",
        body: "Whether it was typed in, imported from a file, sent by the webhook or found by search, who added it, and exactly what was supplied.",
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
        title: "Retry, release or override",
        body: "A failed lead can be retried. A held lead shows why and can be released once you have fixed the cause. A disqualified lead can be overridden unless a country rule blocks it.",
      },
      {
        target: "lead-people",
        title: "People and consent",
        body: "Each person with their addresses and how they were checked. Record consent where someone has agreed to be contacted, or suppress a person for good.",
      },
      {
        target: "lead-add-person",
        title: "Add a person",
        body: "Add someone you know at the company, with a first and last name (or their work email) so the address can be found. Tick that they have consented and say where it came from, and a lead held for consent is released and carries on. Releasing a consent hold without consent only holds it again.",
      },
      {
        target: "lead-edit",
        title: "Edit a lead",
        body: "Change the name, country, priority or campaign. What you set is marked as yours and kept.",
      },
      {
        target: "lead-delete",
        title: "Delete a lead",
        body: "Removes the lead and everything about it for good. You must type its domain to confirm, and a lead that has been emailed cannot be deleted (suppress it instead). You can also block the domain so it is never added again.",
      },
      {
        target: "lead-suppress",
        title: "Do not contact",
        body: "Suppress the whole domain. Their unsent emails are cancelled.",
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
        title: "Six tabs",
        body: "Sender profile, limits, campaigns, country policies, the do-not-contact list (with Forget an address for erasure requests) and mailboxes.",
      },
      {
        target: "sender-profile",
        title: "Confirm your sender profile",
        body: "Every statement here ends up in emails under your name. Read it, keep only what is true, and press Confirm and save. Emails are not written until you do.",
      },
    ],
  },
];
