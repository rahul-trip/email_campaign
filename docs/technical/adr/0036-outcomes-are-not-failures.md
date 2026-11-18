# 0036 · A company with nobody to write to is an outcome, not a failure

- **Status:** accepted, 2026-11-19
- **Context:** Outbound is a funnel: most companies a campaign looks at are meant to drop out. The two stages that find a person and an address raised `StageFailure` when they found none, so the lead went to `failed`, the same status as a timeout or a refused key. The app counted every one in the amber *Needs attention* badge and showed a red *Failed* card first on Today, so an operator saw mostly red even on a good day, and the few emails ready to approve were buried. The engine also retried these leads every 15 minutes, three times, and spent credits to get the same answer.
- **Decision:**
  1. A failed lead carries a `failure_kind` (`error`, `no_person`, `no_email`; migration 0030). `StageFailure` takes a `kind`; the contacts and email stages set it where they mean "nobody to write to".
  2. A broken step is retried soon (15 minutes times the attempts so far), **5** times. An outcome is asked again **24 hours** later, **3** times, then stops.
  3. `domain/outcomes.py::bucket_of` puts every lead in one bucket: `ready`, `working`, `decision`, `screened_out`, `done`. The same rule is written as a SQL filter (`_bucket_filter`) and a test keeps the two equal. The API exposes it (`CompanyOut.bucket`, `StatusOut.buckets`, `GET /api/companies?bucket=`).
  4. A hot lead (fit above 80) that nobody could email is `ready`, so it appears on Hot leads with its LinkedIn message instead of being a dead end.
  5. The web app leads with what a person can use (emails ready, approvable from Today; hot leads), counts only the `decision` bucket in the badge and the bell, and describes a screen-out in grey and calm words.
- **Consequences:** the number of failures a person sees falls to the ones that need them. The limits are constants in `domain/outcomes.py`, not settings. Leads that failed before 0030 are classified from their last error text by the migration, so a few may read as `error`. A lead screened out for want of an email can still be retried by hand (Find people again, Find email again).
- **Alternatives rejected:** hiding failures behind a filter only (the badge and notices would still alarm); a new `screened_out` company status (a second state machine to keep in step, and a lead that fails again would have two ways to stop).
