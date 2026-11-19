# Outbound Engine — User Manual

**Covers:** the application as built through Phase 3 (the engine, the command line, and the web app).
**For:** the person who runs the outreach (the operator). You do not need to read code.
**Not covered yet:** follow-up emails, reading replies, bounce handling, automatic sending and multiple users. Those are Phases 4–6; see [phases/](phases/README.md).

---

## 1. What the application does

You give it companies you want to contact. For each one it:

1. **researches** the company's own website;
2. **finds the right person** and works out their email address, checking that it will not bounce;
3. **writes** a short first email, in your voice, with the legally required footer for the country;
4. **waits for you** to read, edit and approve it;
5. **saves it as a draft** in your mailbox. You press Send yourself, from your normal mail program.

Two rules hold everywhere:

- **Nothing is ever sent by the application.** It only places drafts in your Drafts folder.
- **Nothing is drafted until you approve it.** Approval is checked again at the moment of drafting.

It is built for about 5–50 new companies a week. Everything it buys (searches, email lookups, checks, AI model calls) is measured in **AI credits**.

### What this version does not do

- It writes the **first email only**. There are no automatic follow-ups yet.
- It does **not read replies** or react to bounces.
- It does **not send**. Drafts only.
- Accounts are **invitation only**. There is no sign-up page, no two-step sign-in and no sign-in with Google or Microsoft yet.

See also [section 13](#13-known-limits-in-this-version).

---

## 2. Before you start

You need the following in place once. [README.md](../README.md) has the commands.

| You need | Where it goes | Without it |
|---|---|---|
| Vendor keys: search (Tavily), email finders and verifier (for example Hunter, ZeroBounce, MyEmailVerifier) | `.env` | The run stops with "not configured" and names what is missing |
| A model key (any OpenAI-compatible provider) | `.env` | Research and writing cannot run |
| A connected mailbox | Settings → Mailboxes | The engine works up to "approved" but cannot make drafts or read your Sent folder |
| `SECRETS_KEYS` (encrypts the mailbox passwords and sign-ins; `uv run outbound secrets new-key`) | `.env` | A mailbox cannot be connected |
| An account: `uv run outbound users create` (below), or an invitation from someone who has one | The command line, once | You cannot sign in |
| Email for invitations and password resets: `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM`, `APP_BASE_URL` | `.env` | On your computer the links are printed in the `serve` terminal instead. On the server the app will not start |
| Your **sender profile**: legal name, postal address, registration details, signature | Settings → Sender profile | The writer refuses to produce an email, because the legal footer would have a hole |
| A **campaign**: wanted job titles and a description of your ideal customer | Campaigns | Contacts cannot be ranked and fit cannot be scored well |

Keep `.env` private. It is never committed to git.

---

## 3. Starting and signing in

Open two terminal windows in the project folder.

```bash
uv run outbound serve      # the web app and API, at http://127.0.0.1:8000
uv run outbound worker     # does the work you start from the browser
```

- **Both must be running.** The web app only *queues* a run; the worker carries it out, for every workspace in the database. Every 15 minutes it also retries failed leads, collects catch-all answers, reads the Sent folder and runs any leads that are due. If you press Start run and nothing happens, the worker is not running.
- Open <http://127.0.0.1:8000> and sign in with your **email and password**.
- **The first account** is made on the command line; everyone after that is invited from the app:
  ```bash
  uv run outbound users create --email you@example.com --workspace default
  ```
  It asks for a password: at least 15 characters, and a few ordinary words make a good one. Add `--platform-role superadmin` to make yourself the platform's staff as well.
- **Moving an install from before Phase 6b** (one shared password): `uv run python -m scripts.migrate_first_tenant --name "Your company" --email you@example.com` shows what it would do; add `--apply` to do it. It renames the `default` workspace and makes you its admin and the platform's superadmin.
- The web app listens only on your own computer. Five wrong passwords in a minute from one computer, or ten in 15 minutes for one account, pause sign-in. A sign-in lasts until you have been away for 24 hours, and at most 14 days (8 hours and 3 days for platform staff).
- **Forgot your password?** Ask for a reset link on the sign-in page. It works once, for 30 minutes, and signs you out everywhere else.
- The database is the local file `outbound.db` unless `.env` says `DATABASE_BACKEND=postgres`, which uses `POSTGRES_URL` (the Supabase database) instead. Change that one line to switch.
- First time only: `uv run outbound db upgrade` and `uv run outbound seed` create the database, a default workspace, a default campaign and the country rules.
- **On the server** the app and worker run all the time, at the address your team set up (always https). A deploy sets up the database itself and restarts both processes for a few seconds, so avoid deploying while a run is going. Logs, restarts and CLI commands on the server are in the [deployment guide](technical/operations/deployment.md), section 3; when something goes wrong there, see the [runbooks](technical/operations/runbooks/README.md).

### 3.1 Accounts, invitations and workspaces

- **Workspaces.** A workspace is one company's leads, campaigns, settings and people. Its address in the browser starts with `/w/` and its short name, for example `/w/acme-energy/leads`, so a link you send a colleague opens the same workspace. If you belong to several, the workspace name at the top left switches between them. Opening the bare address (`/`) takes you to the one you used last.
- **Invitations.** Two kinds. A platform admin can invite someone to Outbound itself, from the console's **Users** page: the person sets a password and then starts their own workspace or asks to join one (below). Admins invite people into their own workspace from **Settings → Team**. The invitation email has a link that works once, for 7 days: a new person gives their name, chooses a password and accepts the Terms; someone who already has an account signs in with the invited address and presses **Join**. A newer invitation to the same address replaces the old link.
- **Starting or joining a workspace.** Someone invited to Outbound itself, with no workspace yet, sees **Get started**. **Start a workspace** makes one and the person becomes its admin. **Join a workspace** takes the **join code** that the workspace's admins share (shown in **Settings → Team → Join requests**, where an admin can also make a new code; the old one stops working at once). The request waits for an admin, who gets a number on the **bell** at the top right and finds it under **Settings → Team → Join requests**: **Approve** (choosing member or admin) or **Reject**. The person is told on their own bell and on the Get started page, and can open the workspace once approved. A wrong code is not accepted more than 10 times an hour.
- **If your workspace was deleted.** Your account stays. When you sign in, the Get started page says *Your workspace was deleted* and offers **Ask for a new workspace** instead of starting one: give the company name (and, if you like, its website and a note). The platform team sets it up, you become its admin, and you get an email.
- **Roles.** An **admin** can do everything in the workspace. A **member** does the daily work: adding leads, runs, review, campaigns, suppressing an address. Only admins manage the team, the sender profile and limits, country rules, forgetting a person and deleting a lead; members see a message saying so. A workspace always keeps at least one admin.
- **Your account** (the round button at the top right): change your password, sign out every other device, sign out, or delete your account.
- **Superadmin view (alpha only).** The platform's superadmin can open any workspace to help. A red banner, *Superadmin view of …, read-only*, stays at the top the whole time, nothing can be changed, and every such visit is recorded. **Exit** leaves it.

### 3.2 Setting up a new workspace

A new workspace starts **empty**: your company's name and website, the country rules and one empty campaign, nothing else. When an admin accepts the invitation they land on **Set up your workspace**, four steps (open it again any time at `/onboarding`, or from the **Get started** card on the Dashboard):

1. **Your company:** the sender profile (what the writer may truthfully say, the legal name and postal address the footers print, who signs). Nothing is written until you confirm it.
2. **A mailbox:** where approved emails are saved as drafts. You can skip it and connect one later.
3. **Who to reach:** the job titles you want and your ideal customer. This step cannot be skipped: until the workspace has an active campaign with job titles and an ideal customer, every page except Settings and this setup shows **Create your campaign** (a member sees a note that an admin has to do it). The first campaign is the active one; see 5.8.
4. **Your first leads.**

A tick appears as soon as a step is done, wherever you did it. The **Setup check** in Settings shows the same list: *missing* items stop emails being written; *worth a look* items (DNS, country-rule review, no leads yet) do not.

### 3.3 Plans, AI credits and waiting

Your workspace is on a **plan** that gives a number of **AI credits** a month, counted from the day it started: **Free 100, Starter 2,000, Pro 10,000** by default. Every web search, page read, email lookup, address check and AI model call uses AI credits; an answer reused from earlier (searches for 30 days, addresses for 90) uses none, so **running the same targets again costs nothing**. Adding a company uses no credits itself. **Settings → Plan and usage** shows the month's credits, any extra credits you were given, what is used and what is left; every lead's page, run and report shows the AI credits it used.

When the AI credits run out nothing is lost and nothing fails:

- A company you add is saved as **waiting for AI credits** (on **Add leads**), and becomes a lead when credits are back.
- A lead stops before its next step that uses credits, keeps its status (an approved email stays approved, and is still saved to your mailbox, which uses none) and appears under **Failed leads → Waiting for AI credits**. A step that had already started finishes, so you may go a little past your allowance (a little more than before, as several leads are worked on side by side).
- Search for new companies, **Write it again** and **Ask for changes** wait until credits are back.

Waiting work continues **by itself** as soon as credits are back: when the month renews, when the team who runs the service gives you extra credits or a larger plan, or when they extend your access. **Resume** (on a lead, or **Resume all now**) tries at once; without credits it says when they renew. Past the **access date** the workspace is read-only: you can read everything, but nothing can be added or run until access is extended. **Settings → Plan and usage** has **Ask for more AI credits** (say how many if you know), which works even then.

### 3.4 The guided tour

The first time you sign in on a browser (once setup is done), a one-minute tour opens by itself:
nine steps across seven stops — Welcome, Today, ⌘K search, Emails ready, Failed leads, Leads,
Discovery runs, Campaigns, and a send-off. Each step spotlights the part of the screen it is
about, with a short line on what it does for you; a little rocket moves along the track as you go.

- **Show me / Next** goes on (on the last step it says **Let's go**); **Back** goes back.
- The **→** and **←** keys do the same; **Escape** or **Skip tour** closes it.

It opens once per browser. To see it again, open your account menu and choose **Take the guided tour**.

**For whoever changes the app:** the tour is data. Its steps (text, emoji, the element each points
at) are in `web3/src/tour/steps.ts`; the player is `web3/src/tour/Tour.tsx`. Keep it short: one
step per screen that matters. Give the element `data-tour="name"` and use that name as the step's
`target`. `web3/e2e/tour.spec.ts` walks every step and fails if one points at something missing.

---

## 4. A first email, start to finish

1. **Settings → Sender profile:** fill in your legal name, postal address, registration details and signature. Press **Confirm and save**.
2. **Campaigns:** set the wanted job titles (best first) and describe your ideal customer.
3. **Add leads:** add a company, for example just a website.
4. **Runs:** press **Start run**. Watch the row until it says *Succeeded*.
5. **Review:** read the email, change anything you like, then **Approve**.
6. **Runs:** press **Start run** again. This run saves the approved email as a draft.
7. Open your mail program, find the draft in **Drafts**, check it and press Send.

---

## 5. The screens

The menu on the left groups the screens by what you do there. The numbers next to **Emails ready** and **Failed leads** are how many items wait for you there; the second counts only what a person can unblock, so a company the engine screened out is never in it. **LinkedIn ready** (the LinkedIn page) shows how many messages are written. **Replies** and **Sending** are marked *Soon*: they arrive in later phases.

Across the top:

- **Search** finds a lead by company or domain. Press Enter to open the filtered list; Ctrl+K (Cmd+K on a Mac) jumps to the box from anywhere.
- A chip shows a run that is queued or in progress. If a run stays queued, a red banner says the worker is not running.
- The **workspace name**, next to the logo: switch to another workspace you belong to.
- **Add target**, **Tour**, the **theme** button (light, dark, or follow the computer) and **your account** (your initials): password, sign out everywhere else, sign out.
- A yellow banner reminds you while the sender profile is not confirmed, because no email is written until it is.

On a narrow screen the menu folds away; open it with the button at the top left.

### 5.1 Dashboard

The first screen after signing in.

**The bell** in the top bar (on every page) lists what the engine did, newest first, and each line opens the page it is about: *drafts waiting for review* (and how many are hot), *a hot lead* (once for each lead), *leads that need a decision* (a hold, or a step that broke on every try), *cold drafts approved automatically*, *your run finished* (only for runs you started), *a run failed*, *automatic discovery is paused*, and credit and access warnings. A line you have not read is updated instead of repeated, so a busy day is a few lines, not a list. **Mark all read** clears the count; lines older than 90 days are removed.

- **Emails ready:** the big card at the top says how many emails are waiting, and shows the best three (hot leads first) with the subject and the start of the email; on a phone they are a row you swipe sideways, up to ten emails. **Approve** approves one on the spot (it is saved to your mailbox as a draft within 15 minutes); an email with a skipped check says **Check and approve** and opens it in Review. **Start reviewing** opens the whole queue.
- **LinkedIn ready: hot leads to message:** a compact strip of up to ten hot leads (fit above 80) whose LinkedIn message is written. Swipe or use the arrows to scroll sideways. Each card has the fit score, the start of the note and **Copy note & open**, which copies the note and opens the person's profile; **Full message** opens the LinkedIn ready page, where you can edit, mark sent or skip. Some of these leads have no email we could prove, so LinkedIn is the way in. The strip sits above *Failed leads*, as the sidebar does.
- **This week:** emails approved, how many went out unedited, and new leads.
- **Behind the scenes:** where every company went: *reached you*, *being worked on*, *needs a decision*, *screened out*. Most companies are meant to drop out (they do not fit your brief, nobody suitable works there, or no address could be proven), so a long grey *screened out* bar means the engine is working, not failing. Each box opens those leads.
- **Failed leads:** only what you can unblock: holds (with the reasons), steps that broke on every try, websites to confirm and leads waiting for credits. It is empty on a good day.
- **AI credits** used over the last 30 days, per vendor and per prospect against your budget; **Quality** (how many sent emails went out without an edit, against the 80% target); and **Engine activity**, the last run and what it did.

### 5.2 Emails ready (Review)

This is where you spend most of your time.

- **Company logos:** each lead is marked by its company's own logo (its website's icon, or its initials when it has none) on the lead's page, on every waiting email in the list and on the email being read, and on the email cards on Today.
- **Left:** the emails waiting, hot leads first (a flame beside the name; see *Hot and cold* below). A *Flagged* tag means the application's own checks found a problem. On a phone or a tablet the list becomes a row of cards above the email: swipe sideways and tap one to read it (the arrows and *1 of N* at the top work too).
- **Centre:** the email, exactly as it will be drafted, **including the footer**. The text box is editable. When you change something, a *Your changes* panel shows additions in green and deletions in red. Above it: who it goes to, whether the address is safe to send (*Not verified: you skipped the check* if you did), where it came from and which vendor checked it.
- **Hot and cold.** A lead's fit score decides how much it needs you: above 80 it is **hot** (a flame and the score) and its email always waits here for you; 80 or lower it is **cold**. A lead with no score is neither. With **Approve cold leads' emails automatically** switched on (Settings → Limits and budget, off by default), the engine approves a cold lead's email on its next pass, as *Approved automatically (cold lead)* in that email's history, and the draft is saved in your mailbox like any approved one. It does so even when the writing check flagged the email, so read cold drafts in your mailbox before you send them. It never approves the email of a hot lead, a lead with no score, or an email that relies on a check you skipped, and nothing is ever sent for you. Emails approved this way are left out of the *sent without edits* figure on Reports, because no person chose them.
- **Skipped checks:** if the email relies on a check you skipped (the country rule for this lead or for the workspace, an address used without proof, or a person you confirmed works there), an amber panel lists them. **Approve** stays greyed out until you tick *I know these checks were skipped, and I approve this email anyway*. What you confirmed is recorded.
- **Opens with:** above the email, the dated news item it starts from, linked to its source. Open it and check it is real and stated correctly before approving. If research found no dated news about the company, it says the email opens with a fact from their site instead.
- **When:** each waiting email shows *Written 2 h ago* in the list, and above the text the exact time it was written (and when it last changed). When the address was last checked is shown beside it. The right-hand **History of this email** lists each step of its life (written, edited, approved, drafted, sent), when, and by whom (you or the engine).
- **Right, "Why this lead":** the fit score and its reason, what the research found, the answers to your research questions, and any notes you added.
- **Right, "Checks":** each quality check (length, subject, reading level, one question, no links, no address, no banned phrases, footer present) with a tick or a warning and the reason, then the country, the company type and the country rule with the version used.

| Button | Does |
|---|---|
| **Approve** | Accepts the email as written |
| **Approve with my edit** | Accepts your edited text. Both versions are kept, and how much you changed is recorded |
| **Undo my edits** | Puts the original text back |
| **Ask for changes** (box under the email) | Type how to change it: the tone, the length, what to stress, or facts to add (one click on *More formal*, *Shorter* and the like starts you off). **Rewrite with these changes** rewrites the text as it is in the box, with your own edits, and puts the result there; the diff shows what changed. Ask again as often as you like, edit by hand, then approve: approving keeps it as your version, which teaches the writer like any edit. Your facts are used as given; the legal footer is kept exactly. If the rewrite breaks a check (say, too long) it says so, but you can still approve. Nothing is saved until you approve; what you asked for is kept in the email's history |
| **Write it again** | Throws this email away and has the next run write a new one to the same person, under the current rules and news. Use it when the email misses the point |
| **Reject…** | Ends work on this company. A reason is required and is kept |

Keyboard: **J** and **K** move through the queue, **Ctrl+Enter** in the text approves, **?** lists the shortcuts.

Good to know:

- **Do not remove the footer.** It is the legal text for the country. An edit that deletes it is refused.
- Approving does not draft the email. The draft is made by the **next run**.
- Your edits teach the writer: your most recent corrected emails in the same campaign are shown to it as examples (the number is set in Settings → Limits and budget).
- A *flagged* email is not an error. It means "look carefully here".

### Where a lead goes

Every lead is in one of five groups, and the app words them calmly:

| Group | What it holds | Where you see it |
|---|---|---|
| **Ready for you** | an email waiting for approval; a hot lead nobody could email, with its LinkedIn message | Emails ready, LinkedIn ready |
| **Working on it** | still being researched, or tried again by itself (*Trying again, try 2 of 5*), or a catch-all being resolved | Leads → Working on it |
| **Failed leads** | a hold only you can resolve, or a step that broke on every try (*Stopped after 5 tries*) | Failed leads |
| **Approved & sent** | approved, in your mailbox, in a sequence, replied | Leads → Approved & sent |
| **Screened out** | does not fit, rejected, suppressed, or nobody to write to (*No decision-maker found*, *No email we could prove*) | Leads → Screened out (grey) |

*Nobody to write to* is an answer, not a breakage: the engine asks again **3 times, a day apart**, in case people or addresses turn up, and then the lead is screened out. A step that really broke (a timeout, a refused key) is tried again soon, up to **5 times**. You can always press **Find people again** or **Find email again** on a screened-out lead. A hot lead (fit above 80) that ends this way moves to *Ready for you* so you can message the person on LinkedIn.

### 5.3 Failed leads

*(Called Needs a decision until 2026-11-20. You never have to press Retry: the engine retries a broken step by itself, waiting 15 minutes, 30, 1 hour, 2 and 4 between its five tries. When no vendor can answer (out of credit, or down), a lead waits two hours, then four, eight, sixteen and a day at most, and no try is counted. Retrying a lead costs AI credits, so the page is named for what it holds and the engine retries by itself, with longer waits each time.)*

A lead that stopped for want of an address, or whose last step broke, but has a LinkedIn message written for someone there, is **not** listed here: it counts as a success (*Message on LinkedIn*) and is on **LinkedIn ready**, whatever its fit.

**Filters and sort.** Under the tabs: search by company, website or person; **Hot only**; minimum fit; the step a lead stopped at; its source (found by discovery, added by you, imported, referral); country (when leads are in more than one); and **Sort** by best fit, waiting longest, newest or company, with a button to reverse it. *Showing N of M leads* says how many are left; **Clear** removes every filter.

**What each row tells you, so you can decide whether to retry.** The fit ring and a *Worth checking* flag on hot leads (fit above 80), which are the ones to look at first; the person who would be written to; *Try 3 of 5* and the step that stopped; where the lead came from; the AI credits spent on it so far; and a hint: *Fit 34 is below your minimum (60): probably not worth retrying*, or *A hot lead (fit above 80): worth a look before the others*. **Details** opens why it fits, the full error and the criterion-by-criterion qualification.

Only what waits on a choice of yours, apart from review, grouped by reason, each group saying in plain words why and what fixes it. A lead that is still being tried again, or that the engine screened out, is not here: see *Where a lead goes* below.



- **Held** leads, one group per hold reason (section 7.1). Each row offers the action that resolves it: **Use XX and release** when the research suggested a country, **Add a person with consent** for consent and company-type holds, or *Waiting for the resolver* for catch-all addresses. A lead held on a catch-all address the resolver could not prove has **Find email again** (searches that person's address afresh, with new answers from the vendors, in one run started now); **Find again for all (N)** on the group does the same for every lead in it after you confirm that each lookup uses AI credits.
- **Stopped** leads: a step that broke on every try (5 tries, with longer waits), one group per step (research, qualification, people, the email address, writing the email, the mailbox), with the reason. **Retry now** retries one lead at once; **Retry all (N)** on a group retries every lead in it, and **Retry every stopped lead** (shown when more than one step failed) retries them all. Each lead goes back to its own failed step, in one run started now, after you confirm; a step that pays vendors costs again, while what was already found is reused. A lead that moved on since the page loaded is skipped and counted.
- Leads held because you **messaged them on LinkedIn** have **Release all (N)**: each goes back to finding and writing its email, in one run.
- Country, consent and company-type holds have no button for all of them: each needs its own fix first (a country, a person with consent), and releasing them without it would only hold them again.
- **Websites to confirm:** companies added by name where the website found is not certain. Press **Yes, domain** if the guess is right, or type the right website and press **Use this website**.

The buttons at the top show one kind at a time.

### 5.4 Add leads

Three tabs.

**Add one company.** Fill in whatever you know; one of these is enough:

| You know | Fill in | What the application does |
|---|---|---|
| The website | Website or domain | Uses it directly |
| Only the name | Company name | Searches the web once for the official site. If it is not sure (below 80%), it **asks you** under *Websites to confirm*. A site whose name holds only part of the company's (the group's site for one of its companies) always asks |
| A work email | Known work email | Takes the company from the address; still verifies the address |
| A person and a company | Person + Company name | Finds the company; keeps the person as your first choice |
| A LinkedIn profile | LinkedIn profile URL | Never opens it. A public search of the profile finds the name and company |

Other fields: job title, country (for example `UK`, `DE`, or a name like `Germany`), priority (1 is handled first, 9 last), a campaign, and **notes for the copywriter**. Notes are read by the writer and by the fit judgement, so use them for things like "met at the expo". Tick **Check only, do not save** to see what would happen without adding anything.

**Upload a file.** A CSV or Excel file, up to 2 MB. Column names are matched loosely (for example `Company`, `Website`, `Email`, `Person`, `Title`, `LinkedIn`, `Country`, `Notes`, `Priority`). Press **1. Preview** first: it shows what each row would become and saves nothing. Then **2. Import**.

**Websites to confirm.** The same list as on Failed leads.

**Results for each row**

| Result | Meaning |
|---|---|
| Accepted | A new company was created |
| Merged | The company already exists. Your notes were added to it; nothing was duplicated |
| Needs confirmation | The website is a guess. It waits under *Websites to confirm* |
| Rejected | Not usable. The note says why: no company or website, a free-mail address, a social-media site, or on your do-not-contact list |
| Pending | Only in a preview: the row needs a web search that a preview does not make |

Things that always apply: a company or address on the do-not-contact list is never added; the same website is never added twice; values you type (name, country, priority) are marked as yours and the engine will not overwrite them.

### 5.4a LinkedIn ready

For each confirmed decision-maker who has a LinkedIn profile, the engine writes two texts **right after people are found and before any email address is looked for**, so you can reach them without waiting for an email to be found and checked: a **connection note** (200 characters at most, the limit of a free LinkedIn account) and a **first message** of 60 to 100 words to send once they accept. Only people confirmed to work at the company get one, and only decision-makers (the campaign's job titles, a founder, a C-level, a vice president, a director, or someone you added). A person you want to write to who is not on the list: **Write LinkedIn message** on the lead page.

**Nothing is ever sent from this application**: you copy the text into LinkedIn yourself.

- **Laid out like Emails ready, with the people grouped by company (2026-11-19).** On the left, **Companies** (on a phone, a row to swipe): one card per company with its logo, a flame if it is hot, its fit score, and the people written to there (*Name · Title*, three at most, then *and 2 more*), with *N people*, *no email* and the country under them. On the right, the company you picked: why it fits, an **Open lead** link, and then a message card for **every person** there, one under another, each with its own **Copy & open LinkedIn**, **Mark sent**, **Edit**, **Rewrite** and **Skip**. **J** and **K** (or the arrows) move to the next or previous company; **?** lists the keys. When every message at a company is sent or skipped, the company leaves *To send* and the next one opens. The counts above the page are messages; the line under the filters also says how many companies.
- The **LinkedIn ready** page (named LinkedIn in the address; it was called *Hot leads* until 2026-11-19) lists every message in three tabs: *To send*, *Sent* and *Skipped*. Above the list: search (company, website or person), **Hot only**, **No email** (leads nobody could find a provable address for) and **Has email**, minimum fit, country, and **Sort** (best fit, newest, company A to Z, with a reverse button). The choices are kept in the address, so a filtered view can be bookmarked. The header counts the messages to send, how many are hot and how many have no email we could prove. Each message is a **folding row**: collapsed, it shows the company, person, fit ring, *Hot* and *No email we could prove* flags, the start of the note and **Copy note & open**; opened, it shows the full note and message, why the lead fits and the buttons below. The first row starts open; **Expand all** and **Collapse all** are above the list. 50 rows load at a time (**Show more**). **On a phone** the filters are one line, the search and a **Filters** button that shows how many are on and opens the chips, menus and sort underneath (Failed leads works the same way), and the leads are cards in a row: swipe sideways from one to the next (each snaps into place, and the next one peeks in from the right); from a tablet up they are a list. By default waiting messages list the best fit first (hot leads on top). For each, **Copy & open LinkedIn** beside the note copies it and opens the person's profile in a new tab, ready to paste; the same button beside the message does the same once they accept. Then **Mark sent on LinkedIn**. Without a profile link the buttons only **Copy**; **Open their LinkedIn** still opens the profile on its own. The lead's name links to the lead page.
- **Everything folds, and opens itself only when that helps (2026-11-19).** On the chosen company, **What they do**, **Worth mentioning** and **In the news** are sections with a one-line summary when folded and a count chip; each opens by itself only when it is short, so long research never pushes the messages off the screen. Each **person** is a section too: the first person to write to is open, and so is anyone whose draft needs a look (*Check wording*); the others are folded to their name, title and the first words of their note, with *Sent*, *Skipped* or *Check wording* shown first when it applies (on a phone the state is in that line). What you open or close is remembered for next time, and **Expand all / Collapse all** is above the sections. The note about an email already waiting or sent is not folded: it can change what you send.
- **Before you send (2026-11-19):** the company's name (and, on Emails ready, the name in the email's heading) is a link to its lead page. On LinkedIn ready the chosen company shows what research found that helps you write: what they do, **Worth mentioning**, **Why now**, **In the news** (links), and **Hiring**; and a yellow note when an email to someone there is already waiting for you (with a link into Emails ready) or was already sent, so you do not contact them twice without knowing. Each person shows **First choice** (the engine's pick at that company), their seniority, who found them (*Found by search*, or *Added by you*), **Unconfirmed: check they work here** with the reason, their email address and its check status if there is one, and the state of any email to them.
- The lead page has the same messages in its **LinkedIn** card, under *People and addresses*.
- **Edit** changes the words; what you save is yours and the checks no longer apply. **Rewrite** writes a fresh pair. **Skip** sets one aside (**Use it again** undoes it).
- A message the checks still object to (too long, a link, a leftover placeholder, wording that reads like a template) shows what is wrong in a yellow note, so you edit it before you use it.
- **Mark sent on LinkedIn** is final and holds the lead's email: the lead goes on hold as *Messaged on LinkedIn*, so the person is not contacted twice at once, and an email waiting for review is withdrawn. Release the hold (on the lead page, or under Failed leads) when you want the email found and written as well; it then says in one clause that you already wrote on LinkedIn. A lead whose email is already in the mailbox or sent is not held: the message is only recorded.
- Forgetting a person (Policies and privacy) deletes their messages.

### 5.5 Leads

Every company, 25 to a page, each with its website's icon. Search by name or domain; filter by status or by hold reason. Sort by any of date added, last changed, fit, name, status, country, source or priority: choose it in **Sort**, and the arrow beside it reverses the order; or press a column title (Company, Status, Fit, Changed), and press it again to reverse. The filters are part of the page address, so a filtered list can be bookmarked or shared. Each row shows the status (and the hold reason or error), a small bar of the eight stages with the next one named, country, fit, priority and when it last changed, and a **Journey** link.

**A lead's page** (click its name) shows:

- **The page reads top to bottom in order of importance:** **Research** first (always open), then **Emails**, **People and addresses**, **Add a person**, **LinkedIn**, the **Shared directory**, **Vendor and model calls** and **Activity**; **Country rule**, **Edit this lead**, notes and the **Danger zone** are in the column on the right. To keep the page short, what opens by itself depends on what is inside: *Emails* is open when an email waits for you and otherwise shows one line saying where the email stands; *LinkedIn* opens for a lead with no email we could prove (LinkedIn is its way in) and otherwise says in one line whether messages are written; *People and addresses*, *Vendor calls*, *Activity* and the *Danger zone* start closed and say in one line what is inside. Press a card's title to open it. *People and addresses* opens by itself when the lead needs you there (it failed at the people or email step, or is held for consent), and *Add a person* opens when a link points at it. The run and report pages close their long tables the same way.

- the status, hold reason, company type, country, fit score (a flame when it is above 80) and priority, and which values you set yourself;
- buttons that appear when they apply: **Journey**, **Research again** (any researched lead whose email has not left: the next run reads the site and searches the news afresh, then checks fit, people and address and writes the email again; an email waiting for review or approved is cancelled; what you set yourself is kept and addresses already found are reused at no cost), **Retry** (failed), **Override and qualify** (disqualified, except where a country rule blocks contact: record a person's consent instead);
- for a **held** lead, a panel that says why and what fixes it, with **Release hold**. If the research only *suggested* a country, **Use XX and release** sets it and releases in one step. A hold that needs your decision asks where to resume. For consent and company-type holds it points you to **Add a person with consent**;
- **People and addresses:** each person in rank order, each address with its status, where it came from, which vendor found it and which one checked it. *The email is to this person* marks who the waiting email is written to. A person you added, gave an address to, or recorded consent for always comes first, whatever the campaign's job titles prefer, and only that person's own consent lets them be written to. Each person has:
  - **Edit:** correct the name or title, or give a work email. A new address replaces the old one as the one written to; the old one stays as history. On a lead whose email step failed, saving also retries that step;
  - **Confirm they work here:** shown on a person marked *Unconfirmed: check they work here*. A public search found them, but their profile does not clearly say they work at this company, so they are never looked up or written to until you confirm them. The small line under their name says why (for example, only their own name matches the company's). Open their LinkedIn link to check;
  - **Doesn't work here:** for a person you found does not work at this company (a namesake, or they moved on). They are kept on the lead, set aside under *N found who work elsewhere*, and never looked up or written to; a new search does not add them again. **They do work here** brings them back. It is refused once anything has been written to them (suppress them instead);
  - **Record consent:** choose the basis and write where it came from. Recording the same basis twice keeps one record;
  - **Write to this person instead:** when the email is going to the wrong person. The waiting (or approved, not yet drafted) email is cancelled, this person is put first and the lead goes back to the email step;
  - **Remove:** for someone who does not work here, such as a wrong match from a search. It is refused once anything has been written to them;
  - **Skip the check** (next to an address the check could not prove: *unknown*, *invalid*, a catch-all, or not checked yet): if you know the address works, write why and confirm. It becomes the address written to, no more checks are paid for it, and a lead stopped at the email step goes on. An *invalid* address will probably bounce, so use it only when you are sure. **Check it again** undoes it until the email is approved. The same button is in the journey's *Email address* stage when the lead is stuck there;
  - **Suppress:** never contact them again; their unsent emails are cancelled;
  - **Check who works here** (under the list): look again at who a search found. One search per person reads their current profile headline, free rules place the clear cases, and one model call reads the rest; people whose profile says they work elsewhere are set aside. Anyone you confirmed, added or wrote to is never touched. Research does the same check by itself when it finds people, so a person shown as *Works elsewhere* was set aside because their profile names another company, or only their own name matches the company's;
- **Shared directory:** when another customer's run already verified this person's address, it is used first, at no cost, and still checked once before it is used. The card shows the month it was last verified. **Report wrong detail** (the address, that they have left, their title, LinkedIn, the company name or country) stops the directory using that address until the platform team has checked it. **Report wrong detail** also marks that address invalid in your own workspace, so the engine looks for another. If your plan allows it, tick *Find this lead's email with the vendors instead* to skip the directory for this lead; what the vendors find still updates the directory. Forgetting a person removes them from the directory too, and they are never added again;
- **Find LinkedIn:** on a person with no profile link, one search for their LinkedIn profile. The link is kept only when the profile names the same person (a one-letter spelling difference in the first name is allowed) and names this company; otherwise nothing is saved and it says so. Research also looks for each person it finds (up to ten per lead).
- **A wrong or missing LinkedIn profile:** **Remove** beside a person's LinkedIn link takes it off. To add or correct one, open **Edit** on the person and paste their profile link; it is kept as yours, so research does not replace it.
- **Find more people** (called *Find people again* when nobody at the lead can be written to, or the lead failed at the people or email step): under the list on the lead page, and on the Leads page for the leads shown (the first 20). It opens a small form. **Who to look for:** tick roles (Founder, Co-founder, CEO, CTO, Head of Engineering, Recruiter, Head of Talent, Head of Sales) or add your own, up to four; leave it empty to use the campaign's job titles (Founder, CEO and CTO for a lead with no campaign). **What to do with them:** *Just add them*, *Find their email*, *Write a LinkedIn message*, or *Both*. A search is up to two searches and one model call per lead (a few AI credits), and a LinkedIn message is one more call per person. People are added to the lead (people already there are not touched); only those who work at the company are written to, and the rest wait under *To confirm* until you confirm them. When you search for the default job titles and someone new can be written to, a failed lead goes on at the next run; a search for other roles never restarts the lead. A recruiter is not a decision-maker, so their email is looked for only because you asked for it here.
- **Find email again:** on a person, searches for their address afresh, with new answers from the vendors rather than stored ones, and starts a run. It is offered while no email has been written to the lead (it failed at the email step, is waiting at it, or is held on a catch-all address). Once an email exists, use *Write to this person instead*.
- **Add a person:** someone you know at the company (a first **and** last name, or their work email; optional title). Tick *has given consent*, choose the basis and write the evidence, and the consent is recorded with them; on a lead held for consent the hold is released as well. If the person is already on the lead (the same name, ignoring case and accents, or a first name you added earlier), their card is updated instead of a second one being made;
- **Emails:** each email written, its state, how much you edited it and when it was sent. One waiting for review has **Open in Review**, which opens Review on that email;
- **Research** (the first card, always open): a header with the fit score, a *Hot* flag, the sector and the fit reason, and chips for how many must-haves are met, how many signs they may buy were seen, how many things are worth mentioning and how many news items there are. Then four blocks that fold (the first is always open, a later one opens by itself only when it is short, about five items or fewer; closed, each shows a line saying what is inside, and **Expand all** and **Collapse all** are above them): **How well they fit** (each criterion of the campaign's brief as a card, grouped as must-haves, signs they may buy now and rule-outs, with the verdict, the evidence and a link to its source; *Why now* and *Risks* beside them), **What we learned** (what they do, worth mentioning in an email, products and services, hiring, the technology they use, and what their own site said), **In the news** (recent news about the company and market news that may matter to it, each a dated link to its source) and **Your research questions**. The country rule is the last line;
- **Vendor calls:** every vendor call made for this company: when, which vendor, what, **what was asked** (the search text, the pages read, the person and domain looked up, the address checked, or the model and the start of its instruction), the result with a short note of what came back (*3 results*, *address found*, *2 of 3 pages read*) and the cost. *Cache hit, free* means a stored answer was reused. Calls made before this was kept say *not recorded*;
- **Your values kept:** only appears if the engine found a different value for something you set. Yours was kept; theirs is shown;
- **Activity:** what happened to the lead in plain sentences, newest first, grouped by day (*Draft written*, *Held: Catch-all unverified*, *Email approved*, *Draft saved to the mailbox*). It says *by you* only when you did it. **Show details** adds the small events, and the same event repeating (a step waiting again) shows once with a count;
- **Its campaign is paused:** a note appears when the lead's campaign is not the active one. The lead waits where it is until that campaign is switched on;
- **Edit this lead** (right): name, country, priority and campaign. What you save is marked as yours and kept. If something changed the lead meanwhile, you are asked to reload;
- **Danger zone** (right, red): **Suppress this domain** for everyone at the company, and **Delete permanently…**, which removes the lead for good with its people, addresses, emails, notes and history, and any draft waiting in your mailbox. You must type the lead's domain before the button works, and the server checks it again. You can tick *Also never contact this domain again*. A lead that has already been emailed **cannot** be deleted: suppress it instead. Money already spent stays in the cost totals.

**A lead's journey** (the *Journey* link) tells the whole story of one company:

- what state the lead is in and **what happens next** (and whether the next move is yours), how many of the eight stages are finished, what has been spent on it, and how many people and emails there are;
- the **stage bar** of the eight stages: Intake, Research, Qualification, People, Email address, Copy, Review, and Draft and outreach. Green is done, blue is next for the engine, amber is held or waiting for you, red is failed or stopped, grey is not reached. Click a stage (or use the arrow keys) to read it. The page opens on the stage that needs attention;
- each **stage** shows a summary, its details, any holds or failures, and the vendor calls made with their cost;
- **How this lead arrived:** typed in, imported from a file, sent by the webhook or found by search, who added it and when, exactly what was supplied, and how the website was matched.

It only shows; to act, use **Open the lead to act on it**.

### 5.6 Runs

- **What to run.** *Only my targets* (the usual), *Discover new companies* (the active campaign; choose how many), or both. A run works on up to 50 leads at each step; the rest wait for the next run. Discovered companies must pass the fit minimum; ones you added by hand skip it.
- **How discovery finds companies.** It works from the campaign's brief (**Who we look for** on the Campaigns page; the first run drafts it if nobody has):
  1. **Start-up directories.** When the brief is after start-ups (or any kind of company), it looks in the Y Combinator directory for active companies about the brief's words (matched one by one, so a brief with only a summary and segments still finds companies), in its regions and founding years. Companies found on earlier runs are left out, so each run brings new ones. This costs nothing.
  2. **The UK register.** When the brief's regions include the UK and it has industry (SIC) codes, it asks Companies House for active companies, plcs and LLPs with those codes, founded since the brief's year. This costs nothing. The register has no websites, so each fit needs one search to find its website before it becomes a lead.
  3. **Exa company search** (when your platform has an Exa key). It searches company websites for the brief's summary, and finds companies like your example customers and like this campaign's leads that passed the fit check. About 9 cents a search.
  4. **Pages that list companies.** A model plans up to four web searches for pages that name many companies like the ones you want: rankings, funding round-ups, accelerator cohorts, association members, award lists (for example *energy forecasting start-ups in Europe*). It reads the best pages and notes every company each one describes and what it says about it. Every search takes a new angle, and no page is read twice. Without a model, the searches come from the brief's own words and no page is read.
  5. **Screening.** A company named in two places counts once, as found twice. Companies already screened for this campaign, and companies that are already your leads, are set aside. The model says what each one is to you (a buyer, a vendor to your buyers, a competitor, an investor, an adviser or publisher, or unclear) and scores it against the brief. Only a buyer is added, and only with a score of 50 or more (60 when the text does not make clear what it is); one that hits a *Rule out* line is not added. A company that sells software or services to your buyers is a vendor, not a buyer. If the model cannot answer for a company (its reply fails twice), the company is kept as *Not judged yet, checked again next run* instead of being turned down, and the next run judges those first, before it searches for more. Without a model at all, a company fits when its description uses the brief's words.
  6. **Adding.** The best fits are added as leads, up to the number you asked for (while AI credits are left). A company's website comes from its source, from a link on the page that named it, or from searching its name and then its homepage; when no site's address is the company's name, a model picks its own site from the likeliest results, or none. If no website can be confirmed it is kept as *Fits, no website yet*, looked for once more by the next run, and dropped if it is still missing. Fits beyond the number you asked for wait, and the next run adds them first without searching again.
- **The best sources first.** Places whose leads passed the fit check most often over the last 90 days are asked first and for more; one whose leads rarely pass is asked for half as many (never none). Reports shows the record as *Where good leads come from*.
- A discovered company is renamed from its own website during research. The run's summary says `Discovery added N new leads in M searches`.
- **How many leads a run handles.** A run works on up to 50 leads at each step; the rest wait for the next run. There is nothing to set.
- **Find emails with the vendors, not the shared directory.** Shown when your plan allows skipping the directory. It applies to the leads this run works on (the choice stays on each lead, where it can be changed); what the vendors find still updates the directory.

**Above the list**, one line says whether the worker searches for new companies by itself: *on, about every 6 hours, next search around 14:00*, or why it is paused (switched off, no active campaign, no AI credits left, a run in progress, *Review holds 52 drafts, it resumes below 50*, or the leads already found are still being worked on).

The Runs page lists every run you started, every file import, and the discovery runs the application started for you (see *Finding companies by itself* below), newest first (the last 200). The application's own timer work is not listed: its housekeeping runs, every few minutes, and the passes that move leads along on their own. It opens with the week at a glance (runs, steps completed, new leads found, held or failed, spend). A run moves every company as far as it can go and the list shows, in words, how many moved on, were held, failed or are waiting for credits, how many new companies discovery found, a progress bar while it is going, the time it took and the money spent. **Cancel** stops a run between companies. Click a run's time, or **Open**, for its own page, which has the numbers at the top (time, steps completed, held, failed, spend and cost per step), a step-by-step table, **Where it looked** (each directory and search, with its angle, the pages read and how many companies each named), **Companies it found** (every company, best fit first, where it was found, what the source said, its fit score and the decision: *Added as a lead*, *Does not fit*, *Fits, no website yet*, *Fits, waiting for the next run*, *Not judged yet, checked again next run* or *A lead already*, with the reason; **Make a lead** adds one the screening left out, asking for its website when none is known, as a lead you chose, so it skips the fit check), a table of what each vendor cost (calls, found, reused, errors, average time), and the leads it touched: what it was asked to do, its counts per step and spend, and **every lead it moved on, held, failed or will retry**, with each step it took and the reason or error, failures first. Each lead's name opens the lead, and **Journey** its journey. A lead the run looked at and left alone is not listed. The page fills in while the run is going. The list updates by itself while a run is queued or running.

Run states: *Queued* (waiting for the worker), *Running*, *Succeeded*, *Failed* (the run itself broke; individual companies failing does not make a run fail), *Cancelled*.

### 5.7 Reports

Quality since the start (sent without an edit against the 80% target, flagged share, catch-all share), spend for the period you choose (7, 30 or 90 days, or a year: total, per prospect against your budget, and how many calls were answered from the cache), where leads are held, and cost per vendor: calls, spend and average cost per call, which is what the vendor bake-off decides on. **From a company found to a draft** follows the period you chose: the companies discovery named (and how many of them the model read), what screening decided, where the leads added in that time are now (waiting, disqualified at the fit check, failed at a step, held and why, or ready for review) and how often each vendor failed. The same table is `outbound report funnel --days 30`. **Where good leads come from** lists each place discovery looks (Y Combinator, Companies House, Exa, lists and articles) with how many companies it named over the last 90 days, how many became leads and how many passed the fit check; discovery asks the best ones first.

### 5.7a What the lead page shows from research

The **Research** card at the top of a lead's page lists everything research found, in blocks: how well they fit (a card for each criterion of the brief, with its evidence and source), what we learned (what the company does, findings worth mentioning in an email, products and services, hiring, the technology they use and their own site's news), the news (recent news about them and market news, each a link to its source with its date) and the answers to your research questions. Nothing is cut short: research no longer limits how many products, findings, news items or people it keeps.

When the lead's campaign has a brief (*Who we look for*), **How well they fit** lists every must-have, sign they may buy now and rule that rules a company out, each with *Yes*, *No* or *Not known*, the words research found for it and a link to its source, then **Why now** and **Risks**. The score is worked out from those answers, not guessed: must-haves give up to 80 (a must-have that counts 3 weighs three times as much, and one that is not known counts half; a brief with no must-haves of its own is judged against its summary, its kind of company and its size, so a company that does not match them scores low instead of 60), each sign adds 10 up to 20, and a rule that rules them out makes it 0. A company discovery found whose own site already shows it meets a rule-out is stopped there, at a fraction of the cost of full research (no news, people or company checks), with the rule and the words that showed it as the reason. A lead you added, imported or were referred to is always researched in full. The lead's header shows when it was added and last changed, and each email shows when it was written.

### 5.8 Campaigns

A workspace can keep several campaigns, but **one is active**. The first you make is active; a later one starts paused. **Switch on** (after you confirm) makes a campaign the active one and pauses the previous one, whose leads then wait where they are and lose nothing until it is switched on again; **Pause** stops the active one. Discovery, the Runs page and new targets follow the active campaign, and a paused campaign's cards are closed. Each campaign has its wanted job titles (one per line, best first), the ideal customer, the minimum fit score (0–100), up to 3 research questions and the follow-up days (stored for a later phase). **New campaign** adds one.

Under each campaign, **Who we look for** is its brief: the ideal customer broken into parts the engine can use.

- **What it holds:** a short summary; the kind of company (any, start-ups, small and mid-sized, enterprises, public sector); what must be true (add `(3)` after an essential line, `(2)` after one that matters); what they do; kinds of company; where; what rules a company out (a competitor, for example); signs they may buy now; where such companies are listed (accelerator cohorts, funding round-ups, association members); funding stages; UK SIC codes; and example customers.
- **Draft from the campaign** (later **Draft again**) asks the model to write it from the ideal customer, job titles and research questions above and from section 3 of your sender profile, *What the writer may use*. Drafting again replaces the brief, so save your own changes somewhere first if you want to keep them. Without a model, a plainer brief is made from the ideal customer, where you sell and your target industries.
- **Save brief** keeps your edits. Lists are cleaned the same way as a drafted brief: blank and repeated lines go, and each list keeps at most 12 lines.
- Discovery searches from the brief and research checks every lead against it. The first discovery run for a campaign drafts the brief if nobody has. If a brief has neither *what they do* keywords nor *must haves* (as when the first drafting failed), the next discovery run drafts it once more and fills only the empty parts; what you wrote is kept.
- **A thin brief says so.** A yellow note above the brief lists what is missing: no summary, no must-haves (leads are then judged only against the summary, kind of company and size), no rule-outs (vendors, competitors and companies that are too big are not turned away) and no keywords. A campaign's job titles are checked too: an entry that is not a job (*BESS integrators*) is flagged, and is left out of the people search.
- **Finding companies by itself.** The active campaign, when it says who it is after (the *ideal customer* text or a brief), is searched for new companies about **four times a day** (every 6 hours; Settings → Limits and budget sets 1 to 6 a day) without you pressing anything: the application queues a discovery run for 10 companies and it shows on the Runs page like one you started. It waits when a run is already queued or going, when the last search was less than a gap ago (a search you started counts), when the campaign already has 10 leads still waiting for their emails, when the workspace has no AI credits left, and **when Review already holds 50 emails** (set under *Stop while Review holds*; it resumes as you work them off). A campaign with no ideal customer is never searched. It costs the same as a run you start yourself. *Search for new companies by itself* in Settings switches it off.

### 5.9 Mailboxes

Mailboxes are connected in **Settings → Mailboxes** (the old Mailboxes address opens it). Approved emails are saved as drafts in a mailbox you connect; you read them there and press Send yourself.

- **Connect** with *Microsoft 365 / Outlook* or *Google Workspace / Gmail* (you sign in on the provider's page and allow access to drafts and the Sent folder), or with *Any other (IMAP)*: the server, your address and an **app password**. The IMAP login is tested, and the Drafts and Sent folders found, before anything is saved. A server on a private network address is refused. The Microsoft and Google buttons appear only when the server has those sign-in apps set up.
- Each mailbox shows whether it works, who **signs** from it (name, title, greeting and voice examples; empty fields use the company profile), and its **DNS check**: mail servers (MX), SPF (including how many DNS lookups it needs, at most 10), DKIM (at the provider's own selector first) and DMARC (policy and whether reports are requested), each with what to fix in plain words.
- The **default** mailbox is used by campaigns that do not name one. Members look after the mailboxes they connected; admins look after all of them and choose the default.
- **Test** uses the mailbox once and records the result. **Pause** stops drafting in it (approved emails wait). If access is withdrawn or runs out the mailbox says *Connect again* and emails wait until you connect the same account again. **Disconnect** deletes the stored password or sign-in; drafts already saved stay in the mailbox.

### 5.10 Policies and privacy

| Tab | What it holds |
|---|---|
| **Country rules** | At the top, the switch for the whole workspace: **Switch country rules off…** (it asks first) means no lead is held, blocked or asked for consent because of its country; a red banner then shows on every page, and **Switch country rules back on** undoes it. The do-not-contact list still applies either way. **Release leads the rules no longer hold** lets held leads go on once nothing holds them. Below, the rule (allow, allow with footer, consent required, block) and footer for each country, *Incorporated companies only*, *Only addresses from* (where an address must have come from; none ticked means any), and who reviewed it. A change saves a new version, and every decision records the version it used. **Add country** takes its two letters and a rule; **Remove** deletes a rule, after which that country's leads are held for you. Every change is recorded |
| **Do not contact** | Add an address or a whole domain. It is stored only as a fingerprint, never as text, and asks you to confirm because it cannot be removed |
| **Forget a person** | Erases a person on request (section 10): the address goes on the do-not-contact list, unsent emails are cancelled, drafts are deleted, and their name, title and address are removed |

### 5.11 Settings

Every Save shows what happened next to it: *Saving…*, then a green tick, or the error. In the boxes marked *one per line* press Enter for a new line; blank lines are dropped when you save.

| Tab | What it holds |
|---|---|
| **Setup check** | What is missing before the engine can work well: the confirmed sender profile, the legal name and address, the signature, a campaign with titles and an ideal customer, a mailbox with its DNS checked, and country rules with a named reviewer. Each item links to where it is fixed |
| **Sender profile** | Who you are, in four parts: the legal identity printed in footers, your signature, what the writer may use (*About you*, value propositions, proof points), **so only put true statements there**, and *How you write*: the greeting (Hi, Hello or Dear), what you want from these emails (the closing ask follows it), and up to four emails you have sent before. Those are read for what you offer and how direct you are, never copied: their wording, greeting and bullet lists are not reused. A preview shows the footer for each country as your profile fills it, with any missing field marked. Until you press **Confirm and save**, no emails are written |
| **Sender profile from a file** | At the top of the Sender profile tab: **Download empty file** gives a JSON file with every key (it keeps the format fixed), **Download my current profile** gives the same file filled with what is saved, and **Upload a file** fills the whole profile from a file you edited. Keep the keys exactly; a file with other keys, a wrong greeting (only Hi, Hello or Dear) or too-long text is refused with the reason. Lists are lists of text. An upload replaces what is saved and counts as confirming the profile, so read it afterwards |
| **Mailboxes** | Connect Microsoft 365, Google or an IMAP mailbox, check it, pause it, choose the default and who signs from it (see 5.9) |
| **Plan and usage** | Your plan's AI credits a month, extra credits you were given, what is used and left with a meter, when they renew and until when you have access, and **Ask for more AI credits** (the team who runs the service sees the request). Banners appear everywhere when 80% or all of the credits are used, access is about to end or has ended, or the engine is stopped |
| **Integrations** | The intake webhook: the address other systems POST targets to, and a signing secret you make here (shown once; a new one replaces the old at once). Below it are the **request body** (copyable templates for one target or several, with every field explained) and a complete **example**: a body, a signed curl command and the answer. Admins only |
| **Team** | Who works in this workspace, their role and when they last signed in, and invitations not used yet. Admins invite people (email and role), change roles, remove people, and send an invitation again or withdraw it. Admins also see the workspace's **join code** and the **requests to join** waiting for them, to approve or reject. Members see the list only |
| **Your account** | Change your password (the current one first; other devices are signed out), sign out every other browser and device, or **Delete my account** (asks for your password; your mailboxes are disconnected and a workspace where you are the only person is suspended; a workspace's last admin must name another admin first) |
| **Limits and budget** | Budget per lead in AI credits (blank means no limit; 0 means no paid calls), the shortest and longest first email in words (120 and 200 by default; greeting, sign-off and footer are not counted), how many of your earlier corrections the writer sees, *Only send to proven addresses* (leave this on), *Try common address formats first* (on by default: when a company's email format is not known, first.last@, first@, flast@ and firstlast@ are checked one by one, and one is used only if the checker proves the mailbox exists, before a paid finder is asked; nothing unproven is ever written to), and *Add a footer to every email* (leave this on: your company, postal address and a plain way to say no; the country's footer, or a short default where it has none, also when a country rule is skipped). **Search for new companies by itself** (on by default) with *Searches a day* (1 to 6, default 4) and *Stop while Review holds* (default 50 emails); and **Approve cold leads' emails automatically** (off by default; see 5.2) |

Automatic sending cannot be switched on in this version.

---

## 5a. The new app (web3, being tried out)

A redesigned app does everything the current one does, on the same data. It is switched on by
whoever runs the service (`WEB_APP=web3`); the addresses are the same, so bookmarks keep working.
What is different:

- **Today** replaces the Dashboard: how many drafts wait and how long the oldest has waited, what
  you reviewed today (and your streak), when discovery next runs, the week's approved drafts,
  leads and spend against last week, and folding sections for what needs you, the pipeline, the
  active campaign with its fit scores, where good leads come from, and what happened.
- **Every page section folds.** The first is open; the rest show a one-line summary.
  *Expand all* and *Collapse all* sit above them, and your choice is remembered in this browser.
- **⌘K (Ctrl+K)** opens a search box anywhere: type part of a company's name or website to open
  it, or a page's name to go there.
- **Review** shows the email as it will be drafted, with the action bar always in view and
  *Ctrl+Enter* to approve. "Why this lead" lists each must-have, signal and rule-out with its
  evidence.
- **Leads** has saved views (Hot, Waiting review, On hold…), filters for fit, source and country,
  sorting, and shows each lead's contact, address status and spend.
- **A lead's Journey** is a tab on the lead's page, next to *Overview* and *Activity*.
- **On a phone** the screens that are tables on a laptop change shape so nothing runs off the screen: Discovery runs are a list of cards (when, state, what it did, credits, *Open*), each country rule on Policies and privacy is a block with labelled fields, and Leads leaves out the extra *Journey* link (the company's name opens the lead). In the admin console on a phone, the Customers, Users and Vendors lists are blocks with each value under its column's name, the section bar has full-size buttons, and the banner is short.
- **Discovery runs**: *Start a run now* opens a panel showing what will run, how many companies to
  find (10, 25 or 50), which sources suit your brief and how often their leads passed recently.
  While a run is going, a card at the top shows its six steps and how far it has got, what it has
  found and the AI credits it has used so far, with *Cancel run*. Beside it, *While it runs* says
  how many emails already wait in Emails ready, with a button to start reviewing them.
- **Setting up** opens with a short welcome: pick what you want first (book meetings in a new
  market, work through your own list, or both) and see an example of the finished draft you will
  review, clearly marked as an example. Then come five steps with your progress at the top, and a
  last page with what happens next.
- **A new workspace** starts on a page that says the engine is ready and asks who to look for.
  *Create your campaign* goes to the form; each starter campaign shows who it reaches, where, the
  signal it looks for and who it rules out, and *Use this* fills the form from it.
- **Notifications** (the bell): on a phone the list opens across the screen, under the header.
- **Light, dark or system** theme, from your account menu.

## 6. What happens to a company, step by step

| # | Step | What it does | Where it can stop |
|---|---|---|---|
| 1 | Intake | Works out the company's website and rejects unusable rows | needs confirmation |
| 2 | Research | Reads the home, about, team, news and contact pages; searches the news for recent, dated stories about the company and its market (two searches, a few cents); finds people; works out the country; for UK companies looks for proof it is an incorporated company; scores the fit, criterion by criterion when the campaign has a brief. A discovered company its own site rules out stops after reading the site | failed |
| 3 | Gate | Compares fit with the campaign minimum, then applies the country rule | **disqualified**, **held** |
| 4 | Contacts | Ranks the people against your wanted titles, then by seniority | failed (nobody found) |
| 5 | Email | For the best people in turn: tries an address you gave, one published on the company's site, the company's usual pattern, then each finder in order. **Every address is verified at once** | held, failed |
| 6 | Copy | Writes the email body (120–200 words by default) opening with the most recent dated news it found, adds your greeting, signature and footer, checks it (length, no lists or stock phrases, every fact backed by the research, reads like a person), rewrites up to twice | failed |
| 7 | Review | **You** | rejected |
| 8 | Deliver | Checks everything again and saves a draft in your mailbox | stays *approved* and retries |
| 9 | Sent sync | Notices which drafts you actually sent | |

The company's status shows where it is:

| Status | Meaning |
|---|---|
| new | Accepted, waiting for research |
| researched | Research done |
| qualified | Passed the fit check and the country rule |
| disqualified | Fit too low, or the country forbids cold email |
| contacts found | People ranked |
| email ready | A safe address is chosen |
| **held** | Waiting for something; the reason is shown (section 7) |
| copy ready | An email is waiting for your review |
| approved | You approved it; waiting for the next run to draft it |
| in sequence | Drafted (and later, sent). In this version this is the last step |
| rejected | You rejected it |
| suppressed | On your do-not-contact list, or the country now forbids it |
| failed | A step failed; the lead shows which and why |

---

## 7. When a company is held, disqualified or failed

### 7.1 Held

A held company is waiting. **Release hold** puts it back at the step that held it, where it is checked again.

For the three holds that come from the country rule (*country unknown*, *entity unknown*, *consent required*) **Release hold** is refused while nothing has changed, and the message says what to do. Releasing without fixing the cause would only be held again, so the page does not let it loop. Releasing a hold is not the same as giving consent: consent belongs to a person and is recorded against them.

**Skipping the country rule for one lead.** On the lead page (card *Country rule*) or in its journey at the stage that held it: choose the step to skip it from (*Qualify*, *Find people*, *Find the email address*, *Write the email*, *Draft it in the mailbox*), write why, and press **Skip the country rule**. The rule is then not applied to this lead from that step on; a lead it held goes straight on from where it stopped. You can only skip from the step that stopped it or an earlier one. The do-not-contact list still applies, the footer follows Settings → Limits, and approving the email asks you to confirm the skip. **Apply the country rule again** undoes it until the email is approved. Who skipped it, when and why are in the timeline.

| Hold reason | Meaning | What to do |
|---|---|---|
| country unknown | The country could not be worked out, and the rules depend on it | Set the country under **Edit this lead** (or **Use XX and release** if one was suggested), then release |
| entity unknown | UK company, but nothing shows it is a registered company, and UK rules only allow those | Add a Companies House key so it can be checked, or **Add a person** who has consented (below), then release |
| consent required | The country or company type needs the person's consent first (for example India under the default rules) | Use **Add a person** on the lead page: enter the person who agreed to be contacted, tick that they have consented and say where it came from. The hold is released for you and the next run carries on. Or, if the rule is wrong for you, change it under Policies and privacy → Country rules |
| catch all resolving | The address is on a server that accepts anything, so it cannot be proven by a normal check. It has been sent to a resolver, which answers in 1–3 days | Wait. `outbound tick` collects the answer and releases the company by itself |
| catch all unverified | The resolver could not decide, or there is none | Normally leave it. An unproven address risks a bounce |
| needs operator | The rules for the country are missing or incomplete | Add or review the country's rule under Policies and privacy → Country rules |
| messaged on linkedin | You marked a LinkedIn message to someone at this lead as sent, so the email waits | Release the hold when you want the email found and written too; leave it if LinkedIn is enough |

### 7.2 Disqualified

- **Fit too low:** the research judged the company a poor match. If you disagree, **Override and qualify** on the lead's page.
- **Country forbids cold email** (by default Germany and Austria): it stays disqualified, and *Override and qualify* is not offered. To go ahead, add the person who agreed to be contacted with **Add a person** (ticking that they have consented), or skip the country rule for this lead from *Qualify* (section 7.1). If a country's rule changes to block after a lead was qualified, the lead is **held** at its next step, never ended for good.

### 7.3 Failed

A failed lead shows the step and the reason. The application retries automatically up to 3 times, waiting longer each time; the worker's regular pass (every 15 minutes) does this. You can also press **Retry** on the lead at once.

| Message | Meaning | What to do |
|---|---|---|
| no valid email found for N contact(s) | Every address tried was invalid or unknown. Nothing is wrong with the system | If you know the right address, **Edit** the person and give it (the step is retried), or **Add a person** with their work email. If you know an address the check could not prove does work, press **Skip the check** next to it. A person with only a first name cannot be looked up by the finders (they need a full name), but an address you give is used as it is |
| no decision-maker was found | The site named nobody and the search found nobody | Add a person yourself |
| people were found, but none is a decision-maker | The site and the search named only people who cannot decide to buy (engineers, managers, or no title at all). Emails are written only to a founder, owner, C-level, vice president, director, head of, one of the campaign's job titles, or a person you add or choose | **Add a person** you want to write to (a person you add counts as chosen), then **Retry** |
| the sender profile needs: legal_name, postal_address … | The footer cannot be filled | Fill in those fields in Settings → Sender profile, then Retry |
| the sender profile needs signature_name | Still the placeholder signature | Set your signature, then Retry |
| no contact has an address that is safe to send to | The chosen address is no longer usable | Check the lead's People section |
| budget per prospect used up | The company used its budget of AI credits | Raise it in Settings → Limits and budget if you accept the cost |
| the reply was cut off at the token limit | The model ran out of room, even after one more try (a reasoning model can spend the whole limit thinking) | Raise `LLM_MAX_TOKENS`; for a reasoning model also set `LLM_REASONING_EFFORT=low`, or use a model that does not think at length |
| the model's reply was not valid JSON / did not have the expected shape | The model answered badly twice in a row (it is asked once more automatically). Free models do this often | Retry; or use a stronger model in `LLM_MODEL`. The emails alone can use a separate model: `LLM_COPY_MODEL`, and research alone a faster one: `LLM_EXTRACT_MODEL` (or, in the console, Vendors → AI models → **Use for research**) |
| a 429 from the model | The model's provider is rate-limiting you (common on free models) | Wait and retry, or switch to a paid model |
| a vendor error such as 401 or 429 | A key is wrong or a limit was hit | Check the key and your plan, then Retry |

---

## 8. Country rules (defaults)

These are working defaults, **not legal advice**. Have a lawyer review them before you rely on them, and record who did under Policies and privacy → Country rules.

| Country | Default behaviour |
|---|---|
| United States | Allowed, with a footer: your identity, postal address and how to opt out |
| United Kingdom | Only to incorporated companies (Ltd, PLC, LLP). Anything else is held. Footer includes your registration details and where you found the address |
| Germany, Austria | Blocked (prior consent is required even for business email) |
| France, Netherlands, Ireland, Sweden | Allowed, with a footer |
| Canada | Allowed only if the address was published on the company's site or given by you. A guessed address is held |
| India | Held unless consent is recorded |
| Unknown country | Held until the country is known |
| Any other country | Held until a policy is added |

You can change all of this: edit or remove any country's rule, add any country with any rule, skip the rule for a single lead, or switch country rules off for the workspace (Policies and privacy → Country rules).

The country is taken from what you entered, otherwise from the site (a stated registration, the domain ending, a phone prefix, a UK postcode).

---

## 9. AI credits

- Every paid call is recorded with the AI credits it used, fixed when it is made. A stored answer is reused instead of buying it again: web searches for 30 days, addresses and checks for 90 days. **Running the same targets again costs nothing.**
- **Budget per lead** (Settings → Limits and budget, 50 AI credits by default): before every paid call the application checks the credits the company has used and refuses the call if it would go over.
- Vendor calls are converted at the rate the team who runs the service sets (one AI credit per US cent of vendor cost by default): a web search or page read is about 0.8 credits, an address found by Hunter about 2.5, by ZeroBounce about 16, a MyEmailVerifier check 0.25. AI model calls use the charge set for the model, per million words-pieces (tokens) read and written.
- Calls made before AI credits were introduced (migration 0029) count as none.
- For whoever runs the platform: `MONTHLY_CAPS_MICRO_USD` in `.env` is a dollar safety cap per vendor across a workspace; the console's caps are in AI credits across every customer.

See what you used: `uv run outbound report cost --days 30`, the Reports screen, or *Vendor and model calls* on any lead's page.

---

## 10. Drafts and sending

- Drafts go to the folder named by `DRAFTS_FOLDER` (for Hostinger, `INBOX.Drafts`). They are normal drafts: open, adjust and send.
- Each draft carries a fixed identifier, so even if something fails halfway **a draft is never saved twice**.
- When you send a draft from your mail program, the worker's next regular pass reads your **Sent** folder and matches it: same recipient, same subject (ignoring "Re:"), sent after the draft was made. It then records exactly what went out and how much you changed it.
  - **Do not change the recipient or subject** when sending, or the match cannot be made. If two sent emails could fit one draft, nothing is guessed; it is flagged in the lead's timeline.
- While `outbound worker` runs, it does this pass by itself every 15 minutes (`--tick-minutes` changes it), along with retries and catch-all answers, and runs any leads that are due. Without the worker, run `outbound tick` on a timer instead, for example from cron:
  ```
  */30 * * * * cd /path/to/email_campaign && uv run outbound tick
  ```

---

## 11. The command line

Everything in the browser can also be done from the terminal. Run from the project folder; add `--workspace NAME` or `--database-url URL` if needed.

| Command | Does |
|---|---|
| `uv run outbound targets add --website acme.com --country UK` | Adds one target (also `--company`, `--email`, `--person`, `--title`, `--linkedin`, `--note`, `--priority`; `--validate-only` to test) |
| `uv run outbound targets import FILE [--validate-only]` | Imports a CSV or XLSX |
| `uv run outbound targets pending` / `targets confirm ROW_ID DOMAIN` | Lists and settles unclear rows |
| `uv run outbound run [--limit N] [--only research,gate] [--mode discovery]` | Runs every step over the work that is due |
| `uv run outbound review list` / `show ID` | Lists waiting emails / shows one |
| `uv run outbound review approve ID [--edit FILE]` | Approves, optionally with your edited text from a file |
| `uv run outbound review reject ID --reason "…"` | Rejects |
| `uv run outbound tick` | One housekeeping pass: retries, collects catch-all answers, reads the Sent folder, runs the pipeline |
| `uv run outbound retry` | Sends failed leads back to the step that failed |
| `uv run outbound status` | Counts by status, holds and their reasons, failures |
| `uv run outbound report quality` | How many sent emails went out unedited, how many were flagged, holds by reason |
| `uv run outbound report funnel --days 30` | From companies found to drafts: what discovery named, where the leads are now, which vendors fail |
| `uv run outbound report cost --days 30` | AI credits used per vendor and per company |
| `uv run outbound delete-lead acme.com [--suppress] [--yes]` | Permanently deletes a lead (asks you to type the domain; `--suppress` also blocks the domain) |
| `uv run outbound forget EMAIL` / `suppress VALUE` | Erases a person on request / stops all contact with an address or domain |
| `uv run outbound users create --email EMAIL [--workspace SLUG] [--role admin\|member] [--platform-role admin\|superadmin]` | Makes an account without an invitation (the first admin, or platform staff). Asks for the password |

Message IDs in `review` can be shortened to their first characters, as long as they are unique.

---

## 12. Is it working well?

`uv run outbound report quality` answers the question that matters: **of the first emails you actually sent, how many went out without any edit?** The target is **8 of the first 10**. If you edit most of them, the sender profile, the campaign description or the proof points need work, not the engine.

Also watch:

- the **flagged share**: many flags mean the instructions to the writer are too loose;
- the **held share by reason**: many *catch all* holds mean costly or slow addresses; many *entity unknown* mean you need a Companies House key.

---

## 13. Known limits in this version

Honest list of what is not there yet, so nothing surprises you.

| Limit | Workaround |
|---|---|
| **Changing the address of a person who already has one** is not possible | Add the person again with the right address, and suppress the old one if needed |
| **First email only.** After drafting, a company stays *in sequence*; there are no follow-ups, replies or bounce handling | Phase 4 |
| The copy writer and research use whatever model you configured. A small free model may miss details such as job titles | Use a stronger model for real outreach |
| Scrubby (catch-all resolver) was repaired on 2026-11-16 and accepts and polls a batch; a finished answer has not been seen yet (it takes up to 24 hours). Enrichley, the real-time alternative, refused its key. Companies House, the mailbox, Hunter, ZeroBounce, OrbiSearch and MyEmailVerifier were checked live on 2026-10-19 | After deploying, press *Find email again* on leads held for a catch-all. Run `uv run python -m scripts.live_check` to re-check any vendor |
| Follow-up and Sent-sync behaviour with a real mailbox is not yet exercised by a real send | Try it with a few of your own addresses first |
| No two-step sign-in, sign-up page or sign-in with Google or Microsoft | After the alpha (Phase 6f) |

---

## 13a. Reading the logs

The web app and the worker write one line per event to the terminal they run in (standard error). In a terminal the lines are coloured and easy to read; when the output goes to a file or a service manager they are JSON, one object per line, so any log tool can read them. Two settings in `.env`:

| Setting | Values | Default |
|---|---|---|
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |
| `LOG_FORMAT` | `auto` (readable on a terminal, JSON otherwise), `json`, `console` | `auto` |
| `ENVIRONMENT` | any label, such as `production`; printed on every line | `development` |

Every line has `timestamp` (UTC), `level`, `logger`, `event`, `service`, `version` and `environment`, plus the details of that event. The events worth knowing:

| Event | Tells you |
|---|---|
| `http_request` | method, route, status, `duration_ms`, `request_id`, `client_ip`. The query string is never logged. Warnings are 4xx answers, errors are 5xx |
| `login_failed`, `login_succeeded` | which account (its id, never the address or the password) and from where |
| `superadmin_view` | a superadmin opened a workspace they are not a member of (also kept in the audit log) |
| `run_started`, `run_finished` | the stages, then status, duration, cost and the outcome counts per stage |
| `stage_done`, `guard_refused`, `stage_failed` | one lead at one stage: `company_id`, `stage`, where it went and why |
| `provider_call` | vendor, call, outcome, `cost_micro_usd`, `latency_ms`; `provider_call_blocked` when a budget stopped it; `provider_retry` for each retry with the reason |
| `privacy_action` | a forget or suppress: what was done and counts. The address itself is never logged |
| `unhandled_error` | a bug, with the full traceback |

**Following one request.** When something goes wrong in the browser the message ends with a *Reference*. That is the `request_id`: search the logs for it to see everything that request did. The same id is in the `X-Request-ID` response header, and you may send your own (8 to 64 letters, digits, `.`, `_`, `-`) to follow a request across systems.

**What is never logged:** passwords, API keys, tokens and cookies (their values are replaced by `[redacted]`), the text of emails (only its length), and email addresses (shown as `j***@acme.com`). Keys inside a URL are masked too.

---

## 14. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| The server will not start: "SMTP_HOST is not set" | In production the app must be able to send invitations and resets. Set the `SMTP_*` settings and `EMAIL_FROM` |
| Page loads but shows only "Loading…" or a blank | The web app was not built: `cd web2 && npm ci && npm run build` |
| Something failed in the browser and the message ends "Reference: …" | Search the logs for that reference (see 13a); the line with `unhandled_error` has the cause |
| A lead fails with "has no first and last name" | A person was saved with one word. Open the lead, press **Edit** on the person, give both names (or a work email) and **Save and retry the email step** |
| A button fails with "The server has no such endpoint" (or, on an older version, "Method Not Allowed") | The page is newer than the running server. Stop `uv run outbound serve` and `uv run outbound worker` and start them again. Do this after every update |
| **Start run** does nothing | The worker is not running: `uv run outbound worker` |
| "not configured" when running | A needed vendor key is missing; the message names it |
| Everything is held for *country unknown* | The sites are not revealing a country. Give the country when adding targets |
| Nothing appears in Drafts | No mailbox is connected, it is paused or says *Connect again* (Settings → Mailboxes), or the approved email has not been through a run yet. Run once more |
| A run shows *failed* | See the error shown in the run's progress, or in the worker's terminal |
| You cannot sign in | Check the email and password; after five wrong tries wait a minute. Or use **Forgot password** |
| "You are not a member of that workspace" | Your link points at a workspace you were removed from, or never joined. Ask its admin for an invitation |
| An invitation link says it is not valid any more | It was used, replaced by a newer invitation, revoked, or is older than 7 days. Ask for a new one |
| You see old data | The server reads the database in `DATABASE_URL` (default `outbound.db`). Make sure you started it against the one you mean |

---

## 14c. Asking to be removed from the lead directory

Anyone, with or without an account, can open `/remove-my-data` on the app's address, enter their work email and follow the link that is sent to it. Confirming removes that address and anything noted about it from the shared directory and stops it being added again. The link works once, for a day. No customer is told who asked.

---

## 14b. Opt-outs and bounces

Each tick the engine reads the inbox of every connected mailbox for replies to your emails. A reply that asks to be left alone ("unsubscribe", "remove me", "do not contact me") puts the person on the do-not-contact list, cancels their other emails and deletes their drafts. An email that bounces for good marks the address invalid, adds it to the list, and moves the lead on to the next person. Other replies are kept for you; the engine does not act on them yet. Mail that is not about one of your emails is never kept.

---

## 14a. The admin console (platform staff)

Platform admins and superadmins open **Admin console** from the user menu (or the workspace chooser). An amber **ADMIN · ALPHA** strip marks it. Its header has a bell for the platform team: it says when a vendor's key is being refused, when a vendor is out of credit (for example Tavily's plan limit), and when something crashed (a run, the 15-minute pass, a platform job, or a server error, with the reference to look up in the log). Each alert appears once a day for a key and at most once an hour for a crash; key and credit alerts are also emailed. Clicking one opens the page that fixes it, usually **Vendors and keys**. It has eight pages:

- **Overview:** a **Worker** card (is the process that runs everyone's work alive, how many workspaces it is working on, how many runs wait and for how long, and late 15-minute passes: *Keeping up*, *Behind* or *Not responding*), customers, leads added, drafts made, AI credits used and what they cost the platform in dollars (staff only), what waits for credits, and what needs a decision (credit requests, expiring access, mailbox problems, customers waiting to be deleted). People whose workspace was deleted and who asked for a new one are listed under **Asked for a new workspace**: **Make the workspace** (you can change its name) makes a new, empty workspace with them as its admin and emails them; **Dismiss** says no.
- **Customers:** search and filter; **Invite customer** creates the workspace and emails its first admin. A customer's page has **Grant AI credits** (added to each month's allowance until the grant ends, by default the end of this month; optionally resuming waiting work at once), **Extend access**, a plan change, a status change (active, paused, suspended), **Delete the customer** (under **More**: type its name to confirm; it closes at once, everyone in it is signed out, and its leads, emails, mailboxes and settings are deleted after 30 days, during which **Restore the customer** brings it back; tick *now* to skip the 30 days; its members keep their accounts), overrides (monthly AI credits, people, mailboxes and the rest), members, mailboxes and activity. A customer past its access date is read-only until you extend it.
- **Members and mailboxes of a customer:** on its page, the Members tab changes a person's role or removes them (a workspace always keeps one admin), and the Mailboxes tab can **Force reconnect** a mailbox, so nothing is saved through it until the customer signs in to it again. Both are recorded in the audit log.
- **Users:** disable or enable an account, sign it out everywhere, and (superadmin) set a platform role or **Delete** an account for good (its mailboxes are disconnected, a workspace with only that person is suspended, and the last superadmin or a workspace's last admin cannot be deleted).
- **Plans:** Free, Starter and Pro, each with its AI credits a month, budget per lead, people, mailboxes, campaigns and features. **Superadmins** edit the catalog, choose the default for new customers and set **what an AI credit stands for** (one US cent of vendor cost by default; calls already made keep their credits); other staff see it read-only and give extra credits on a customer's page. A saved change applies to every customer on the plan.
- **Vendors and keys:** the keys of each paid service, always shown as `••••` and their last four characters. A vendor can have up to **three keys**: each call uses one of them at random, and a key that is refused, rate limited or out of credit is skipped for the vendor's next key in the same call, so one bad key never stops work. **Add key** (while there are fewer than three) or **Replace** takes effect on the worker's next run, and the old key is kept 30 days (**Roll back**). **Remove** stops using a key; it too can be rolled back for 30 days. Each key has its own **Reveal** (shown once and recorded in the audit log) and **Test**, which makes one small real call with that key (a one-word model reply, a one-result search, or one address checked: a fraction of a cent) and says whether it works; the two catch-all resolvers have no cheap check and say so. A vendor that rejects our key three or more times in a day shows *key refused* and staff are emailed once a day until it is fixed; only refusals of the key now in use count, so replacing the key clears the flag at once. **Pause** makes the engine ignore a vendor. For Hunter, ZeroBounce, MyEmailVerifier and OrbiSearch the row also shows **what the vendor says the account has left** (searches or credits, and when Hunter's reset; it is free to ask and is checked about every ten minutes). An email finder whose account is empty is **paused by itself** (*out of credit*), staff are told in the bell and by email, and the worker **resumes it by itself** once its balance shows credit again; one staff paused by hand is never resumed for them. While no finder can answer, leads that need an email wait with "no email finder is answering", use no attempt, and are tried again every couple of hours, so top up (or add another finder) and they go on without you pressing Retry. Each vendor shows the AI credits its calls used this month and what it billed the platform, and can have a monthly cap in AI credits: when its calls across every customer reach it the vendor is paused and staff are emailed. **AI models** lists the models staff added. **Add a model** asks for everything a model needs: a name and code, the provider type (OpenAI-compatible for DeepInfra, Groq, Together, OpenRouter or your own server; OpenAI; Anthropic; Google Gemini; Ollama; GitHub Copilot), the model's name at the provider, the base URL (required for OpenAI-compatible), its API key (stored encrypted, never shown again; empty uses the Language model key), temperature, max tokens, reasoning effort, and its AI credits per million input and output tokens. **Make default** switches every model call to it from the next call, with no restart; **Use for writing** makes another model of the same provider write emails; **Test** makes one tiny real call; **Go back to the environment's settings** undoes the choice. Below, *Environment settings and other charges* holds the older settings used while no default is chosen, with **what each model's calls use**: AI credits per million tokens read (input) and written (output). A model with no charge set uses no credits, and the card says so.
- **Lead directory:** how many companies, people and addresses the shared directory holds, how often it answered this month and what that saved, and the reports customers sent about wrong details (**Accept correction** removes the address for good; **Reject** serves it again). A search shows which sources confirmed one address or domain. Nothing here says which customer contributed or asked.
- **Settings:** stop the engine for everyone (typed confirmation), an announcement banner, and the alpha-only superadmin switch.
- **Audit log:** every admin change, filterable, with a CSV export.

---

## 15. Glossary

| Term | Meaning |
|---|---|
| **Anchor** | The one piece of information a target starts from: a website, name, email, person or LinkedIn profile |
| **Campaign** | A set of wanted job titles, an ideal-customer description and settings |
| **Catch-all** | A mail server that accepts mail for any address, so a normal check cannot tell whether the person exists |
| **Domain** | The company's website name without extras, for example `acme.com` |
| **Draft** | An email saved in your Drafts folder, not sent |
| **Fit score** | 0–100: how well a company matches your ideal customer |
| **Flagged** | The application's own checks found something to look at |
| **Footer** | The legal text at the end of the email that depends on the country |
| **Held** | Waiting for something outside the engine's control |
| **Linter** | The automatic checks on an email: length, reading level, one question, no links, no banned phrases |
| **Provenance** | Where an email address came from: given by you, published on the site, a database, or guessed from a pattern |
| **Suppressed** | On the do-not-contact list; never contacted |
| **Tick** | One housekeeping pass, run on a timer |
| **Verify** | Checking, without sending, whether an address can receive mail |
| **Waterfall** | Trying email finders one after another, checking each result, and stopping at the first good one |
| **Worker** | The background process that carries out runs started in the browser |
