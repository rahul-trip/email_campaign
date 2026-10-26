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

It is built for about 5–50 new companies a week, at no more than $0.50 of vendor spend per company.

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
- **On the server** the app and worker run all the time, at the address your team set up (always https). A deploy sets up the database itself and restarts both processes for a few seconds, so avoid deploying while a run is going. Logs, restarts and CLI commands on the server are in [DEPLOY.md](DEPLOY.md), section 3.

### 3.1 Accounts, invitations and workspaces

- **Workspaces.** A workspace is one company's leads, campaigns, settings and people. Its address in the browser starts with `/w/` and its short name, for example `/w/acme-energy/leads`, so a link you send a colleague opens the same workspace. If you belong to several, the workspace name at the top left switches between them. Opening the bare address (`/`) takes you to the one you used last.
- **Invitations.** Admins invite people from **Settings → Team**. The invitation email has a link that works once, for 7 days: a new person gives their name, chooses a password and accepts the Terms; someone who already has an account signs in with the invited address and presses **Join**. A newer invitation to the same address replaces the old link.
- **Roles.** An **admin** can do everything in the workspace. A **member** does the daily work: adding leads, runs, review, campaigns, suppressing an address. Only admins manage the team, the sender profile and limits, country rules, forgetting a person and deleting a lead; members see a message saying so. A workspace always keeps at least one admin.
- **Your account** (the round button at the top right): change your password, sign out every other device, or sign out.
- **Superadmin view (alpha only).** The platform's superadmin can open any workspace to help. A red banner, *Superadmin view of …, read-only*, stays at the top the whole time, nothing can be changed, and every such visit is recorded. **Exit** leaves it.

### 3.2 Setting up a new workspace

A new workspace starts **empty**: your company's name and website, the country rules and one empty campaign, nothing else. When an admin accepts the invitation they land on **Set up your workspace**, four steps (open it again any time at `/onboarding`, or from the **Get started** card on the Dashboard):

1. **Your company:** the sender profile (what the writer may truthfully say, the legal name and postal address the footers print, who signs). Nothing is written until you confirm it.
2. **A mailbox:** where approved emails are saved as drafts. You can skip it and connect one later.
3. **Who to reach:** the job titles you want and your ideal customer.
4. **Your first leads.**

A tick appears as soon as a step is done, wherever you did it. The **Setup check** in Settings shows the same list: *missing* items stop emails being written; *worth a look* items (DNS, country-rule review, no leads yet) do not.

### 3.3 Plans, credits and waiting

Your workspace is on a **plan** that allows so much of each step per month, counted from the day it started. The Free plan allows **5 leads found by search and 5 leads you add**; the other steps are not limited. Each step is counted **once per lead**: researching a lead again, retrying a failure or rerunning a run costs nothing more. Writing a lead's email again, or asking for changes to it, costs one *rewrite* each time.

When an allowance runs out nothing is lost and nothing fails:

- A company you add over the limit is saved as **waiting for credits** (on **Add leads**), and becomes a lead when credits exist.
- A lead that reaches a step with no credit stops there, keeps its status (an approved email stays approved) and appears under **Needs attention → Waiting for credits**.
- Search never looks for more companies than the credits left.

Waiting work continues **by itself** as soon as credits exist: when the month renews, when the team who runs the service adds credits or raises a limit, or when they extend your access. **Resume** (on a lead, or **Resume all now**) tries at once; without a credit it says when the allowance comes back. Past the **access date** the workspace is read-only: you can read everything, but nothing can be added or run until access is extended. **Settings → Plan and usage** has **Ask for more credits**, which works even then.

### 3.4 The guided tour

The first time you sign in on a browser, a short tour opens by itself. It walks through each screen in order (Welcome, which also shows the workspace switcher and your account button, Add leads, Runs, Review, Needs attention, Leads, a lead's journey, acting on a lead, Reports, Settings, Policies and privacy), dimming the page and outlining the part it is explaining.

Every step has these buttons:

1. **Next** goes to the next step. On the last step it says **Finish**.
2. **Back** goes to the previous step.
3. **Skip section** leaves the rest of the section you are in and jumps to the first step of the next one, opening that screen for you. On the last section it ends the tour.
4. **End tour** closes it. Pressing Escape does the same.

The tour opens once per browser; ending or finishing it is remembered, and it will not come back by itself. To see it again, press **Tour** at the top right of any page.

The two sections about a single lead open your most recent lead. If you have none yet, they say so; add a target and start a run, then take the tour again. A step whose part of the screen has nothing to show yet (for example the review queue when it is empty) is shown in the middle of the page.

**For whoever changes the app:** the tour is data, not code. Its text and the element each step points at are in `web2/src/tour/steps.ts`; the player is `web2/src/tour/Tour.tsx`.

- New screen: add a section to `steps.ts` (in the order a person would meet it) and a `place` for it.
- New feature or changed screen: add or edit a step. Give the element `data-tour="name"` (or `tour="name"` on a `Card` or `Tabs`), and use the same name as the step's `target`.
- Removed or renamed element: change or delete the step. `web2/e2e/tour.spec.ts` walks every step against a real lead and fails if a step points at something that no longer exists, so a forgotten step shows up in the checks.
- Keep this section of the manual in step with the sections in `steps.ts`.

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

The menu on the left groups the screens by what you do there. The numbers next to **Review** and **Needs attention** are how many items wait for you there. **Replies** and **Sending** are marked *Soon*: they arrive in later phases.

Across the top:

- **Search** finds a lead by company or domain. Press Enter to open the filtered list; Ctrl+K (Cmd+K on a Mac) jumps to the box from anywhere.
- A chip shows a run that is queued or in progress. If a run stays queued, a red banner says the worker is not running.
- The **workspace name**, next to the logo: switch to another workspace you belong to.
- **Add target**, **Tour**, the **theme** button (light, dark, or follow the computer) and **your account** (your initials): password, sign out everywhere else, sign out.
- A yellow banner reminds you while the sender profile is not confirmed, because no email is written until it is.

On a narrow screen the menu folds away; open it with the button at the top left.

### 5.1 Dashboard

The first screen after signing in.

- **Needs you:** emails to review, leads on hold (with the reasons), failed leads and websites to confirm. Each card opens the list behind it.
- **Pipeline:** how many companies sit at each of the eight stages, from Intake to Drafted, and how many left the main path (held, disqualified, failed, rejected, suppressed). Click a stage to open those leads.
- **Spend** over the last 30 days, per vendor and per prospect against your budget; **Quality** (how many sent emails went out without an edit, against the 80% target); and **Engine activity**, the last run and what it did.

### 5.2 Review

This is where you spend most of your time.

- **Left:** the emails waiting. A *Flagged* tag means the application's own checks found a problem. On a narrow screen the list is hidden; use the arrows and *1 of N* at the top.
- **Centre:** the email, exactly as it will be drafted, **including the footer**. The text box is editable. When you change something, a *Your changes* panel shows additions in green and deletions in red. Above it: who it goes to, whether the address is safe to send (*Not verified: you skipped the check* if you did), where it came from and which vendor checked it.
- **Skipped checks:** if the email relies on a check you skipped (the country rule for this lead or for the workspace, an address used without proof, or a person you confirmed works there), an amber panel lists them. **Approve** stays greyed out until you tick *I know these checks were skipped, and I approve this email anyway*. What you confirmed is recorded.
- **Opens with:** above the email, the dated news item it starts from, linked to its source. Open it and check it is real and stated correctly before approving. If research found no dated news about the company, it says the email opens with a fact from their site instead.
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

### 5.3 Needs attention

Everything that waits on you apart from review, grouped by reason, each group saying in plain words why and what fixes it:

- **Held** leads, one group per hold reason (section 7.1). Each row offers the action that resolves it: **Use XX and release** when the research suggested a country, **Add a person with consent** for consent and company-type holds, or *Waiting for the resolver* for catch-all addresses.
- **Failed** leads, with the step, the reason and when the automatic retry is due; **Retry now** retries at once.
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

**Websites to confirm.** The same list as on Needs attention.

**Results for each row**

| Result | Meaning |
|---|---|
| Accepted | A new company was created |
| Merged | The company already exists. Your notes were added to it; nothing was duplicated |
| Needs confirmation | The website is a guess. It waits under *Websites to confirm* |
| Rejected | Not usable. The note says why: no company or website, a free-mail address, a social-media site, or on your do-not-contact list |
| Pending | Only in a preview: the row needs a web search that a preview does not make |

Things that always apply: a company or address on the do-not-contact list is never added; the same website is never added twice; values you type (name, country, priority) are marked as yours and the engine will not overwrite them.

### 5.5 Leads

Every company, 25 to a page. Search by name or domain; filter by status or by hold reason. The filters are part of the page address, so a filtered list can be bookmarked or shared. Each row shows the status (and the hold reason or error), a small bar of the eight stages with the next one named, country, fit, priority and when it last changed, and a **Journey** link.

**A lead's page** (click its name) shows:

- the status, hold reason, company type, country, fit score and priority, and which values you set yourself;
- buttons that appear when they apply: **Journey**, **Research again** (any researched lead whose email has not left: the next run reads the site and searches the news afresh, then checks fit, people and address and writes the email again; an email waiting for review or approved is cancelled; what you set yourself is kept and addresses already found are reused at no cost), **Retry** (failed), **Override and qualify** (disqualified, except where a country rule blocks contact: record a person's consent instead);
- for a **held** lead, a panel that says why and what fixes it, with **Release hold**. If the research only *suggested* a country, **Use XX and release** sets it and releases in one step. A hold that needs your decision asks where to resume. For consent and company-type holds it points you to **Add a person with consent**;
- **People and addresses:** each person in rank order, each address with its status, where it came from, which vendor found it and which one checked it. *The email is to this person* marks who the waiting email is written to. A person you added, gave an address to, or recorded consent for always comes first, whatever the campaign's job titles prefer, and only that person's own consent lets them be written to. Each person has:
  - **Edit:** correct the name or title, or give a work email. A new address replaces the old one as the one written to; the old one stays as history. On a lead whose email step failed, saving also retries that step;
  - **Confirm they work here:** shown on a person marked *Unconfirmed: check they work here*. A public search found them, but their profile does not clearly say they work at this company, so they are never looked up or written to until you confirm them. Remove them if they do not;
  - **Record consent:** choose the basis and write where it came from. Recording the same basis twice keeps one record;
  - **Write to this person instead:** when the email is going to the wrong person. The waiting (or approved, not yet drafted) email is cancelled, this person is put first and the lead goes back to the email step;
  - **Remove:** for someone who does not work here, such as a wrong match from a search. It is refused once anything has been written to them;
  - **Skip the check** (next to an address the check could not prove: *unknown*, *invalid*, a catch-all, or not checked yet): if you know the address works, write why and confirm. It becomes the address written to, no more checks are paid for it, and a lead stopped at the email step goes on. An *invalid* address will probably bounce, so use it only when you are sure. **Check it again** undoes it until the email is approved. The same button is in the journey's *Email address* stage when the lead is stuck there;
  - **Suppress:** never contact them again; their unsent emails are cancelled;
- **Add a person:** someone you know at the company (a first **and** last name, or their work email; optional title). Tick *has given consent*, choose the basis and write the evidence, and the consent is recorded with them; on a lead held for consent the hold is released as well. If the person is already on the lead (the same name, ignoring case and accents, or a first name you added earlier), their card is updated instead of a second one being made;
- **Emails:** each email written, its state, how much you edited it and when it was sent. One waiting for review has **Open in Review**, which opens Review on that email;
- **Research:** the summary, the fit reason, **recent news about the company** and **market news that may matter to it** (each a dated link to its source), the findings, your research questions' answers and the country rule;
- **Vendor calls:** every vendor call made for this company: when, which vendor, what, the result and the cost. *Cache hit, free* means a stored answer was reused;
- **Your values kept:** only appears if the engine found a different value for something you set. Yours was kept; theirs is shown;
- **Timeline:** everything that happened, in order, and whether you or the engine did it;
- **Edit this lead** (right): name, country, priority and campaign. What you save is marked as yours and kept. If something changed the lead meanwhile, you are asked to reload;
- **Danger zone** (right, red): **Suppress this domain** for everyone at the company, and **Delete permanently…**, which removes the lead for good with its people, addresses, emails, notes and history, and any draft waiting in your mailbox. You must type the lead's domain before the button works, and the server checks it again. You can tick *Also never contact this domain again*. A lead that has already been emailed **cannot** be deleted: suppress it instead. Money already spent stays in the cost totals.

**A lead's journey** (the *Journey* link) tells the whole story of one company:

- what state the lead is in and **what happens next** (and whether the next move is yours), how many of the eight stages are finished, what has been spent on it, and how many people and emails there are;
- the **stage bar** of the eight stages: Intake, Research, Qualification, People, Email address, Copy, Review, and Draft and outreach. Green is done, blue is next for the engine, amber is held or waiting for you, red is failed or stopped, grey is not reached. Click a stage (or use the arrow keys) to read it. The page opens on the stage that needs attention;
- each **stage** shows a summary, its details, any holds or failures, and the vendor calls made with their cost;
- **How this lead arrived:** typed in, imported from a file, sent by the webhook or found by search, who added it and when, exactly what was supplied, and how the website was matched.

It only shows; to act, use **Open the lead to act on it**.

### 5.6 Runs

- **What to run.** *Only my targets* (the usual), *Discover new companies* (the application searches the web for companies matching a campaign's ideal-customer description; choose which campaign and how many), or both. Discovered companies must pass the fit minimum; ones you added by hand skip it. A discovered company is named from its own website during research, never from the article or report that led to it, and articles and documents in the search results are skipped.
- **Leads per stage.** At most this many companies are handled by each step in one run (default 50).

A run moves every company as far as it can go and lists, per step, how many moved on, were held or failed, plus the time it took and the money spent. **Cancel** stops a run between companies. Click a run's time, or **Open**, for its own page: what it was asked to do, its counts per step and spend, and **every lead it moved on, held, failed or will retry**, with each step it took and the reason or error, failures first. Each lead's name opens the lead, and **Journey** its journey. A lead the run looked at and left alone is not listed. The page fills in while the run is going. The list updates by itself while a run is queued or running.

Run states: *Queued* (waiting for the worker), *Running*, *Succeeded*, *Failed* (the run itself broke; individual companies failing does not make a run fail), *Cancelled*.

### 5.7 Reports

Quality since the start (sent without an edit against the 80% target, flagged share, catch-all share), spend for the period you choose (7, 30 or 90 days, or a year: total, per prospect against your budget, and how many calls were answered from the cache), where leads are held, and cost per vendor: calls, spend and average cost per call, which is what the vendor bake-off decides on.

### 5.8 Campaigns

Each campaign has its wanted job titles (one per line, best first), the ideal customer, the minimum fit score (0–100), up to 3 research questions and the follow-up days (stored for a later phase). **New campaign** adds one.

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
| **Mailboxes** | Connect Microsoft 365, Google or an IMAP mailbox, check it, pause it, choose the default and who signs from it (see 5.9) |
| **Plan and usage** | Your plan, what each allowance has used and has left, when the allowances renew and until when you have access, any extra credits you were given, and **Ask for more credits** (the team who runs the service sees the request). Banners appear everywhere when a step is at 80% or used up, access is about to end or has ended, or the engine is stopped |
| **Integrations** | The intake webhook: the address other systems POST targets to, and a signing secret you make here (shown once; a new one replaces the old at once). Admins only |
| **Team** | Who works in this workspace, their role and when they last signed in, and invitations not used yet. Admins invite people (email and role), change roles, remove people, and send an invitation again or withdraw it. Members see the list only |
| **Your account** | Change your password (the current one first; other devices are signed out), and sign out every other browser and device |
| **Limits and budget** | Budget per prospect (blank means no limit; 0 means no paid calls), the shortest and longest first email in words (120 and 200 by default; greeting, sign-off and footer are not counted), how many of your earlier corrections the writer sees, *Only send to proven addresses* (leave this on), and *Add a footer to every email* (leave this on: your company, postal address and a plain way to say no; the country's footer, or a short default where it has none, also when a country rule is skipped) |

Automatic sending cannot be switched on in this version.

---

## 6. What happens to a company, step by step

| # | Step | What it does | Where it can stop |
|---|---|---|---|
| 1 | Intake | Works out the company's website and rejects unusable rows | needs confirmation |
| 2 | Research | Reads the home, about, team, news and contact pages; searches the news for recent, dated stories about the company and its market (two searches, a few cents); finds people; works out the country; for UK companies looks for proof it is an incorporated company; scores the fit | failed |
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

### 7.2 Disqualified

- **Fit too low:** the research judged the company a poor match. If you disagree, **Override and qualify** on the lead's page.
- **Country forbids cold email** (by default Germany and Austria): it stays disqualified, and *Override and qualify* is not offered. To go ahead, add the person who agreed to be contacted with **Add a person** (ticking that they have consented), or skip the country rule for this lead from *Qualify* (section 7.1). If a country's rule changes to block after a lead was qualified, the lead is **held** at its next step, never ended for good.

### 7.3 Failed

A failed lead shows the step and the reason. The application retries automatically up to 3 times, waiting longer each time; the worker's regular pass (every 15 minutes) does this. You can also press **Retry** on the lead at once.

| Message | Meaning | What to do |
|---|---|---|
| no valid email found for N contact(s) | Every address tried was invalid or unknown. Nothing is wrong with the system | If you know the right address, **Edit** the person and give it (the step is retried), or **Add a person** with their work email. If you know an address the check could not prove does work, press **Skip the check** next to it. A person with only a first name cannot be looked up by the finders (they need a full name), but an address you give is used as it is |
| no decision-maker was found | The site named nobody and the search found nobody | Add a person yourself |
| the sender profile needs: legal_name, postal_address … | The footer cannot be filled | Fill in those fields in Settings → Sender profile, then Retry |
| the sender profile needs signature_name | Still the placeholder signature | Set your signature, then Retry |
| no contact has an address that is safe to send to | The chosen address is no longer usable | Check the lead's People section |
| per-prospect budget used up | The company hit its spend ceiling | Raise it in Settings → Limits and budget if you accept the cost |
| the reply was cut off at the token limit | The model ran out of room, even after one more try (a reasoning model can spend the whole limit thinking) | Raise `LLM_MAX_TOKENS`; for a reasoning model also set `LLM_REASONING_EFFORT=low`, or use a model that does not think at length |
| the model's reply was not valid JSON / did not have the expected shape | The model answered badly twice in a row (it is asked once more automatically). Free models do this often | Retry; or use a stronger model in `LLM_MODEL`. The emails alone can use a separate model: `LLM_COPY_MODEL` |
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

## 9. Money

- The ceiling is **$0.50 per company** by default (Settings → Limits and budget). Before every paid call the application checks the company's spend so far and refuses the call if it would go over.
- Every call is recorded with its cost. A stored answer is reused instead of buying it again: web searches for 30 days, addresses and checks for 90 days. **Running the same targets again costs nothing.**
- Approximate default prices the application assumes (change them in `.env` with `PROVIDER_PRICES`): a web search or page read about $0.008 (research now makes two extra news searches per company, about $0.016 more), an address found by Hunter about $0.025, by ZeroBounce about $0.16, a MyEmailVerifier check $0.0025. Model use is billed by your model provider.
- To stop one vendor overspending in a month, set `MONTHLY_CAPS_MICRO_USD` in `.env` (amounts in millionths of a dollar).
- In the first live test, two companies cost $0.051 in total.

See what you spent: `uv run outbound report cost --days 30`, the Reports screen, or *Vendor calls* on any lead's page.

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
| `uv run outbound report cost --days 30` | Spend per vendor and per company |
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
| Scrubby (catch-all resolver) has not worked live: its configured address did not answer. Companies House, the mailbox, Hunter, ZeroBounce, OrbiSearch and MyEmailVerifier were checked live on 2026-10-19 | Confirm Scrubby's API address in your Scrubby account. Run `uv run python -m scripts.live_check` to re-check any vendor |
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

## 14a. The admin console (platform staff)

Platform admins and superadmins open **Admin console** from the user menu (or the workspace chooser). An amber **ADMIN · ALPHA** strip marks it. It has seven pages:

- **Overview:** customers, leads added, drafts made, spend, what waits for credits, and what needs a decision (credit requests, expiring access, mailbox problems).
- **Customers:** search and filter; **Invite customer** creates the workspace and emails its first admin. A customer's page has **Grant credits** (optionally resuming waiting work at once), **Extend access**, a plan change, a status change (active, paused, suspended), per-step limit overrides, members, mailboxes and activity. A customer past its access date is read-only until you extend it.
- **Users:** disable or enable an account, sign it out everywhere, and (superadmin) set a platform role.
- **Plans:** edit the catalog and choose the default for new customers. A saved change applies to every customer on the plan.
- **Vendors and keys:** the key of each paid service, always shown as `••••` and its last four characters. **Add key** or **Replace** takes effect on the worker's next run, and the old key is kept 30 days (**Roll back**). **Reveal** shows a key once and is recorded in the audit log. **Pause** makes the engine ignore a vendor. The language-model settings (model, address, temperature) are here too.
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
