# Phase 6f — Launch readiness (after the alpha)

**Status:** not in the alpha. It lists what must be true before sign-up opens to the public.

**Goal:** the product is safe to offer to anyone:
- stronger sign-in;
- no all-seeing role;
- verified Google and Microsoft apps;
- the directory's legal steps done;
- an independent security test;
- tested backups.

**Depends on:** 6e. Some items can start earlier, as noted.

**Gate:**
- the launch checklist below is signed;
- the penetration test has no open high findings;
- a restore drill has passed.

## Checklist

### Access

- [ ] **MFA,** required for platform roles and workspace admins. Either TOTP built into the `local` identity adapter, or a move to Supabase Auth or WorkOS behind the same `IdentityProvider` port (6b).
- [ ] **A support role with tenant-granted access:**
  - the workspace admin grants time-boxed, read-only access;
  - every view is audited and visible to the customer.
  
  The alpha's **superadmin role is removed**.
- [ ] Owner and viewer roles, if customers ask for them.
- [ ] Social sign-in (Google, Microsoft) with `openid email profile` only, separate from mailbox consent.

### Mailbox providers

- [ ] **Google:**
  - app verification;
  - the **CASA** security assessment for the restricted Gmail scopes: a lab-verified scan, revalidated every year, priced from about $540 to a few thousand dollars.

  Apply during 6c, because this takes weeks.
- [ ] **Microsoft:** publisher verification done (started in 6c).

### Lead directory (from 6g)

- [ ] A legitimate-interests assessment and a DPIA.
- [ ] GDPR Art. 14 notices to each person.
- [ ] US data-broker registration where it applies, including California DROP processing.
- [ ] Vendor terms checked, Hunter's first, and source filters added if needed.

### Legal and vendors

- [ ] Terms, AUP, Privacy Policy, DPA and the sub-processor list published.
- [ ] DPAs signed with the sub-processors, DeepInfra included.
- [ ] Paid vendor plans sized for the expected customers.

### Security and operations

- [ ] An external penetration test, checked against OWASP ASVS 5.0 Level 2, with its findings fixed.
- [ ] A staging environment: its own Supabase project and Doppler config, and the deploy workflow pointed at it.
- [ ] Supabase point-in-time recovery, and a restore drill recorded.
- [ ] Error tracking tagged by workspace; uptime checks; alerts on worker heartbeat, vendor failures and spend caps.
- [ ] A load test with N fake customers. The fair-share claim (6a) holds, and the database connection budget fits.
- [ ] Open sign-up switched on with its abuse controls (6e).

## Gate record

- Date:
- Penetration test (company, date, open findings):
- Google verification and CASA (dates):
- Restore drill:
- Checked by:
