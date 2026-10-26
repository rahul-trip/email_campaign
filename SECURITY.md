# Security policy

Outbound handles personal data (names, work email addresses, consent records) and holds vendor credentials and a mailbox login, so please report security problems privately.

## Reporting a vulnerability

- **Do not open a public issue** for a security problem.
- Report it through GitHub's **private vulnerability reporting** for this repository: *Security → Report a vulnerability*. If that is not available to you, contact the maintainer, [@rahul-trip](https://github.com/rahul-trip), on GitHub and ask for a private channel.
- Include what you found, how to reproduce it, and what you think the impact is. Please do not include real personal data or live credentials. If you came across any, say so and we will rotate or erase them.

You should get an acknowledgement within 5 working days. We will tell you what we plan to do and roughly when.

## Scope

**In scope:**

- the code in this repository: `outbound/`, `web2/`, `scripts/`, `deploy/`, `Dockerfile`;
- its CI and deploy workflows.

**Out of scope:**

- the legacy `agent/` and `web/` packages, which are being retired;
- the vendors' own services;
- the shared VM's other application.

## Supported versions

Only the commit currently deployed from `main` is supported. There are no maintained release branches.

## How the system is secured

The [threat model](docs/technical/security/threat-model.md) describes the trust boundaries, threats and mitigations. The [tech debt and risks register](docs/technical/tech-debt-and-risks.md) lists the known security gaps openly. A finding already listed there is still welcome if you can show it is worse than described.

If a secret has leaked, follow [the secret-leaked runbook](docs/technical/operations/runbooks/secret-leaked.md).
