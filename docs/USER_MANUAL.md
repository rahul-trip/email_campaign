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
- There is **one login** for one operator.

See also [section 13](#13-known-limits-in-this-version).

---

## 2. Before you start

You need the following in place once. [README.md](../README.md) has the commands.

| You need | Where it goes | Without it |
|---|---|---|
| Vendor keys: search (Tavily), email finders and verifier (for example Hunter, ZeroBounce, MyEmailVerifier) | `.env` | The run stops with "not configured" and names what is missing |
| A model key (any OpenAI-compatible provider) | `.env` | Research and writing cannot run |
| Your mailbox login (IMAP): `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `FROM_NAME` | `.env` | The engine works up to "approved" but cannot make drafts or read your Sent folder |
| A web login: `OPERATOR_PASSWORD_HASH` and `SESSION_SECRET` | `.env` | The web app will not start |
| Your **sender profile**: legal name, postal address, registration details, signature | Settings → Sender profile | The writer refuses to produce an email, because the legal footer would have a hole |
| A **campaign**: wanted job titles and a description of your ideal customer | Settings → Campaigns | Contacts cannot be ranked and fit cannot be scored well |

Keep `.env` private. It is never committed to git.

---

## 3. Starting and signing in

Open two terminal windows in the project folder.

```bash
uv run outbound serve      # the web app and API, at http://127.0.0.1:8000
uv run outbound worker     # does the work you start from the browser
```

- **Both must be running.** The web app only *queues* a run; the worker carries it out. If you press Start run and nothing happens, the worker is not running.
- Open <http://127.0.0.1:8000> and sign in with the password you chose when you created `OPERATOR_PASSWORD_HASH`.
- The web app listens only on your own computer. Five wrong passwords in a minute locks sign-in for a minute. A sign-in lasts 12 hours.
- First time only: `uv run outbound db upgrade` and `uv run outbound seed` create the database, a default workspace, a default campaign and the country rules.

### 3.1 The guided tour

The first time you sign in on a browser, a short tour opens by itself. It walks through each screen in order (Welcome, Targets, Runs, Review, Leads, a lead's journey, acting on a lead, Settings), dimming the page and outlining the part it is explaining.

Every step has three buttons:

1. **Next** goes to the next step. On the last step it says **Finish**.
2. **Skip section** leaves the rest of the section you are in and jumps to the first step of the next one, opening that screen for you. On the last section it ends the tour.
3. **End tour** closes it. Pressing Escape does the same.

The tour opens once per browser; ending or finishing it is remembered, and it will not come back by itself. To see it again, press **Tour** at the top of any page.

The two sections about a single lead open your most recent lead. If you have none yet, they say so; add a target and start a run, then take the tour again.

**For whoever changes the app:** the tour is data, not code. Its text and the element each step points at are in `web/src/tour/steps.ts`; the player is `web/src/tour/Tour.tsx`.

- New screen: add a section to `steps.ts` (in the order a person would meet it) and a `place` for it.
- New feature or changed screen: add or edit a step. Give the element `tour="name"` (on a `Card`) or `data-tour="name"`, and use the same name as the step's `target`.
- Removed or renamed element: change or delete the step. `web/e2e/tour.spec.ts` walks every step against a real lead and fails if a step points at something that no longer exists, so a forgotten step shows up in the checks.
- Keep this section of the manual in step with the sections in `steps.ts`.

---

## 4. A first email, start to finish

1. **Settings → Sender profile:** fill in your legal name, postal address, registration details and signature. Save.
2. **Settings → Campaigns:** set the wanted job titles (best first) and describe your ideal customer.
3. **Targets:** add a company, for example just a website.
4. **Runs:** press **Start run**. Watch the row until it says *succeeded*.
5. **Review:** open the email, read it, change anything you like, then **Approve**.
6. **Runs:** press **Start run** again. This step saves the approved email as a draft.
7. Open your mail program, find the draft in **Drafts**, check it and press Send.

---

## 5. The screens

The top bar has five sections. A number next to **Review** is how many emails are waiting for you.

### 5.1 Review

This is where you spend most of your time.

- **Left:** the emails waiting. A red *flagged* tag means the application's own checks found a problem (see below).
- **Centre:** the email, exactly as it will be drafted, **including the footer**. The text box is editable. When you change something, a *Your changes* panel shows additions in green and deletions in red.
- **Right, "Why this lead":** the company, its fit score and the reason, what the research found, the research questions' answers, and any notes you added.
- **Right, "Checks":**
  - whether the linter passed (length, reading level, one question, no links, no banned phrases, footer present);
  - the country and whether the company is confirmed as an incorporated company;
  - each problem found, in plain words;
  - the country-rule decision, with the version of the rule used.

Buttons:

| Button | Does |
|---|---|
| **Approve** | Accepts the email as written |
| **Approve with my edit** | Accepts your edited text. Both versions are kept, and how much you changed is recorded |
| **Reject** | Ends work on this company. A reason is required and is kept |

Good to know:

- **Do not remove the footer.** It is the legal text for the country. An edit that deletes it is refused.
- Approving does not draft the email. The draft is made by the **next run**.
- Your edits teach the writer: your most recent corrected emails in the same campaign are shown to it as examples (the number is set in Settings → Limits).
- A *flagged* email is not an error. It means "look carefully here". Typical flags: wrong length, a claim in the opening line that the research does not support, a missing footer.

### 5.2 Targets

Three ways to add companies, plus a place to settle unclear ones.

**Add a target.** Fill in whatever you know; one of these is enough:

| You know | Fill in | What the application does |
|---|---|---|
| The website | Website or domain | Uses it directly |
| Only the name | Company name | Searches the web once for the official site. If it is not sure (below 80%), it **asks you** |
| A work email | Known work email | Takes the company from the address; still verifies the address |
| A person and a company | Person + Company name | Finds the company; keeps the person as your first choice |
| A LinkedIn profile | LinkedIn profile URL | Never opens it. A public search of the profile's title finds the name and company |

Other fields: job title, country (for example `UK`, `DE`, or a name like `Germany`), priority (1 is handled first, 9 last), a campaign, and **notes for the copywriter**. Notes are read by the writer and by the fit judgement, so use them for things like "met at the expo".

Tick **Check only, do not save** to see what would happen without adding anything.

**Upload a CSV or Excel file.** Column names are matched loosely (for example `Company`, `Website`, `Email`, `Person`, `Title`, `LinkedIn`, `Country`, `Notes`, `Priority`). Press **Preview** first: it shows what each row would become and saves nothing. Then **Import after preview**. Maximum 2 MB.

**Results for each row**

| Result | Meaning |
|---|---|
| accepted | A new company was created |
| merged | The company already exists. Your notes were added to it; nothing was duplicated |
| needs confirmation | The website is a guess. It appears under *Waiting for your confirmation* |
| rejected | Not usable. The note says why: no company or website, a free-mail address, a social-media site, or on your do-not-contact list |
| pending | Only in preview: the row needs a web search that preview does not make |

**Waiting for your confirmation.** For each row you see what you typed and the application's guess. Press **Yes, domain** if the guess is right, or type the correct website and press **Use this website**.

Things that always apply: a company or address on the do-not-contact list is never added; the same website is never added twice; values you type (name, country, priority) are marked as yours and the engine will not overwrite them.

### 5.3 Leads

Every company, newest first, 25 to a page. Search by name or domain; filter by status or by hold reason.

**A lead's page** shows:

- the status, hold reason, country, fit score, and the last error if it failed;
- buttons that appear when they apply: **Retry** (failed), **Override and qualify** (disqualified, except where a country rule blocks contact: record a person's consent instead);
- for a **held** lead, a panel that says why and offers **Release hold**. If the research only *suggested* a country, **Use XX and release** sets it and releases in one step. A hold that needs your decision asks where to resume;
- **People and addresses:** each person in rank order, each address with its status, where it came from (*provenance*), which vendor found it and which one checked it. Each person has **Record consent** (choose the basis and write where it came from) and **Suppress** (never contact them again; their unsent emails are cancelled);
- **Edit this lead:** name, country, priority and campaign. What you save is marked as yours and kept. If someone else changed the lead meanwhile, you are asked to reload;
- **Suppress this domain** at the bottom, for everyone at the company;
- **Emails:** each email written, its state, and how much you edited it;
- **Waterfall:** every vendor call made for this company: when, which vendor, what, the result and the cost. *cache hit* means a stored answer was reused at no cost;
- **Field history:** only appears if the engine tried to change something you set. Your value is kept;
- **Timeline:** everything that happened, in order.

**A lead's journey** (the *Journey* link in the leads table, and the button on a lead's page) is a dashboard that tells the whole story of one company:

- the **header** says what state the lead is in, **what happens next** (and whether the next move is yours), how many of the eight stages are finished, what has been spent on it, and how many people and emails there are;
- the **stage bar** shows the eight stages: Intake, Research, Qualification, People, Email address, Copy, Review, and Draft and outreach. Green is done, blue is next up for the engine, amber is held or waiting for you, red is failed or stopped, grey is not reached. Click a stage (or use the arrow keys) to read it. The page opens on the stage that needs attention;
- each **stage** shows a summary, its details (what the research found, the fit score and country policy, the people and their titles, each address and how it was verified, the email and its checks, your edits, the draft), any holds or failures that happened during it, and the vendor calls made to get there with their cost. A call is counted against the stage the lead was moving towards when it was made;
- **How this lead arrived** shows whether it was typed in, imported from a file, sent by the webhook or found by search, who added it and when, exactly what was supplied, and how the website was matched.

It only shows; to retry, release or edit, use the lead's page.

### 5.4 Runs

- **Mode.** *Only my targets* (the usual), *Discover new companies* (the application searches the web for companies matching your campaign's ideal-customer description), or both. Discovered companies must pass the fit minimum; ones you added by hand skip it.
- **Leads per stage.** At most this many companies are handled by each step in one run (default 50).
- **Companies to discover.** Only for the discovery modes.

A run moves every company as far as it can go, step by step, and reports counts per step and the money spent. **Cancel** stops a run between companies. The page updates by itself while a run is queued or running.

Run states: *queued* (waiting for the worker), *running*, *succeeded*, *failed* (the run itself broke; individual companies failing does not make a run fail), *cancelled*.

The per-prospect budget is shown under the form. When a company has used its budget, no more paid calls are made for it.

### 5.5 Settings

Until you press **Confirm and save** on the sender profile, a notice says it is not confirmed and no emails are written. A blank per-prospect budget means no limit; 0 means no paid calls. **Do not contact** also has **Forget an address**, which erases a person on request (see section 10).

| Tab | What it holds |
|---|---|
| **Sender profile** | Who you are. The legal name, postal address, registration details and contact details are printed in footers. Signature name and title end every email. *About you*, value propositions and proof points are what the writer draws on, **so only put true statements there** |
| **Limits** | Budget per prospect; how many of your earlier corrections the writer sees; and *Only send to proven addresses* (leave this on) |
| **Campaigns** | Wanted job titles (best first), ideal customer, minimum fit score (0–100), up to 3 research questions, and follow-up days (stored for a later phase) |
| **Country policies** | The rule and footer for each country. Each change raises a version number that every decision records. There is a field for who reviewed it |
| **Do not contact** | Add an address or a whole domain. It is stored only as a fingerprint, never as text. You can add but not remove |
| **Mailboxes** | Record a mailbox and press **Check DNS** to see whether its domain has SPF, DKIM and DMARC set up |

Automatic sending cannot be switched on in this version.

---

## 6. What happens to a company, step by step

| # | Step | What it does | Where it can stop |
|---|---|---|---|
| 1 | Intake | Works out the company's website and rejects unusable rows | needs confirmation |
| 2 | Research | Reads the home, about, team, news and contact pages; finds people; works out the country; for UK companies looks for proof it is an incorporated company; scores the fit | failed |
| 3 | Gate | Compares fit with the campaign minimum, then applies the country rule | **disqualified**, **held** |
| 4 | Contacts | Ranks the people against your wanted titles, then by seniority | failed (nobody found) |
| 5 | Email | For the best people in turn: tries an address you gave, one published on the company's site, the company's usual pattern, then each finder in order. **Every address is verified at once** | held, failed |
| 6 | Copy | Writes the five parts of the email, assembles it, adds the footer, checks it, rewrites up to twice | failed |
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

| Hold reason | Meaning | What to do |
|---|---|---|
| country unknown | The country could not be worked out, and the rules depend on it | Set the country (see the limit in section 13), then release |
| entity unknown | UK company, but nothing shows it is a registered company, and UK rules only allow those | Add a Companies House key so it can be checked, or confirm by other means, then release |
| consent required | The country or company type needs the person's consent first | Only continue if you hold real consent; record it, then release |
| catch all resolving | The address is on a server that accepts anything, so it cannot be proven by a normal check. It has been sent to a resolver, which answers in 1–3 days | Wait. `outbound tick` collects the answer and releases the company by itself |
| catch all unverified | The resolver could not decide, or there is none | Normally leave it. An unproven address risks a bounce |
| needs operator | The rules for the country are missing or incomplete | Add or review the country's policy under Settings → Country policies |

### 7.2 Disqualified

- **Fit too low:** the research judged the company a poor match. If you disagree, **Override and qualify** on the lead's page.
- **Country forbids cold email** (by default Germany and Austria): it stays disqualified. Pressing *Override and qualify* will not get it through, because the country check runs again before the next step and stops it. Only a recorded consent changes that, and recording consent has no screen yet (section 13).

### 7.3 Failed

A failed lead shows the step and the reason. The application retries automatically up to 3 times, waiting longer each time, when you run `outbound tick`. You can also press **Retry** on the lead at once.

| Message | Meaning | What to do |
|---|---|---|
| no valid email found for N contact(s) | Every address tried was invalid or unknown. Nothing is wrong with the system | Nothing to retry. Adding a known address to an existing company is not possible on screen yet (section 13); for a new company, fill in the email when you add it |
| no decision-maker was found | The site named nobody and the search found nobody | Add a person yourself |
| the sender profile needs: legal_name, postal_address … | The footer cannot be filled | Fill in those fields in Settings → Sender profile, then Retry |
| the sender profile needs signature_name | Still the placeholder signature | Set your signature, then Retry |
| no contact has an address that is safe to send to | The chosen address is no longer usable | Check the lead's People section |
| per-prospect budget used up | The company hit its spend ceiling | Raise it in Settings → Limits if you accept the cost |
| the reply was cut off at the token limit | The model ran out of room | Raise `LLM_MAX_TOKENS` in `.env` |
| a vendor error such as 401 or 429 | A key is wrong or a limit was hit | Check the key and your plan, then Retry |

---

## 8. Country rules (defaults)

These are working defaults, **not legal advice**. Have a lawyer review them before you rely on them, and record who did under Settings → Country policies.

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

The country is taken from what you entered, otherwise from the site (a stated registration, the domain ending, a phone prefix, a UK postcode).

---

## 9. Money

- The ceiling is **$0.50 per company** by default (Settings → Limits). Before every paid call the application checks the company's spend so far and refuses the call if it would go over.
- Every call is recorded with its cost. A stored answer is reused instead of buying it again: web searches for 30 days, addresses and checks for 90 days. **Running the same targets again costs nothing.**
- Approximate default prices the application assumes (change them in `.env` with `PROVIDER_PRICES`): a web search or page read about $0.008, an address found by Hunter about $0.025, by ZeroBounce about $0.16, a MyEmailVerifier check $0.0025. Model use is billed by your model provider.
- To stop one vendor overspending in a month, set `MONTHLY_CAPS_MICRO_USD` in `.env` (amounts in millionths of a dollar).
- In the first live test, two companies cost $0.051 in total.

See what you spent: `uv run outbound report cost --days 30`, or the Waterfall on any lead.

---

## 10. Drafts and sending

- Drafts go to the folder named by `DRAFTS_FOLDER` (for Hostinger, `INBOX.Drafts`). They are normal drafts: open, adjust and send.
- Each draft carries a fixed identifier, so even if something fails halfway **a draft is never saved twice**.
- When you send a draft from your mail program, the next `outbound tick` reads your **Sent** folder and matches it: same recipient, same subject (ignoring "Re:"), sent after the draft was made. It then records exactly what went out and how much you changed it.
  - **Do not change the recipient or subject** when sending, or the match cannot be made. If two sent emails could fit one draft, nothing is guessed; it is flagged in the lead's timeline.
- Set `outbound tick` to run on a timer (every 15–30 minutes). Example for cron:
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
| `uv run outbound auth hash-password` | Makes the value for `OPERATOR_PASSWORD_HASH` |

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
| **Editing a saved target** (its country, name or priority) has no screen, although the system supports it. This matters most for a *country unknown* hold | Add the target again with the country filled in. This does **not** change an existing company, so for an existing one ask for the screen to be added |
| **Recording consent** for a person has no screen | Not available from the browser yet |
| **Adding an email address or person to a company that already exists** is not possible: adding the same website again only adds your notes | Fill in everything when you first add a company |
| **Releasing a *needs operator* hold** from the browser fails with "no default" | Fix the underlying policy under Country policies; resuming at a chosen step is not offered on screen yet |
| **Removing a person's data on request** (the "forget" action) is built but has no command or screen | Phase 4 |
| The **Mailboxes** screen records a mailbox and checks its DNS. Drafting and the Sent sync use the mailbox login in `.env`, not this list | Keep the two the same |
| **First email only.** After drafting, a company stays *in sequence*; there are no follow-ups, replies or bounce handling | Phase 4 |
| The copy writer and research use whatever model you configured. A small free model may miss details such as job titles | Use a stronger model for real outreach |
| Some vendors have not been exercised live: ZeroBounce, OrbiSearch, Scrubby, Companies House and the mailbox | Test each with a few of your own addresses first |
| One workspace, one login | Phase 6 |

---

## 14. Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| The web app will not start: "The web app needs a login" | `OPERATOR_PASSWORD_HASH` or `SESSION_SECRET` is missing in `.env` |
| Page loads but shows only "Loading…" or a blank | The web app was not built: `cd web && npm ci && npm run build` |
| **Start run** does nothing | The worker is not running: `uv run outbound worker` |
| "not configured" when running | A needed vendor key is missing; the message names it |
| Everything is held for *country unknown* | The sites are not revealing a country. Give the country when adding targets |
| Nothing appears in Drafts | No mailbox login in `.env`, or the approved email has not been through a run yet. Run once more |
| A run shows *failed* | See the error shown in the run's progress, or in the worker's terminal |
| You cannot sign in | Check the password; after five wrong tries wait a minute |
| You see old data | The server reads the database in `DATABASE_URL` (default `outbound.db`). Make sure you started it against the one you mean |

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
