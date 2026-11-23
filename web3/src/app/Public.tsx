/**
 * The pages outside a workspace: signing in, a forgotten password, an invitation, and `/`, which
 * opens the right workspace. They are few and plain, so they are picked by path here instead of
 * by the workspace router, and each one leaves with a full page load.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Building2, Eye, EyeOff } from "lucide-react";
import { LogoMark } from "../ui/Logo";
import { useEffect, useState, type ReactNode } from "react";
import { ApiProblem, client, ok } from "../api/client";
import { Button, Callout, Checkbox, Field, Input, Problem } from "../ui/core";
import { go, homeFor, inWorkspace, rememberWorkspace, useMe, type Me } from "./session";

const MIN_PASSWORD = 15;

/** Only a path on this site, so a crafted link cannot send someone elsewhere after signing in. */
export function safeNext(value: string | null): string | null {
  return value && value.startsWith("/") && !value.startsWith("//") && !value.startsWith("/\\") ? value : null;
}

export function PublicApp() {
  const { pathname, search } = window.location;
  const params = new URLSearchParams(search);
  if (pathname === "/sign-in") return <SignIn next={safeNext(params.get("next"))} email={params.get("email") ?? ""} />;
  if (pathname === "/forgot-password") return <ForgotPassword />;
  if (pathname === "/remove-my-data") return <RemoveMyData token={params.get("token") ?? ""} />;
  if (pathname === "/reset-password") return <ResetPassword token={params.get("token") ?? ""} />;
  if (pathname === "/oauth/callback") return <OAuthReturn params={params} />;
  const invite = pathname.match(/^\/invite\/([^/]+)\/?$/);
  if (invite) return <Invitation token={decodeURIComponent(invite[1]!)} />;
  return <Home path={pathname === "/" ? null : pathname + search} />;
}

// ------------------------------------------------------------------ frame

function Frame({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <main className="flex items-center justify-center px-5 py-12">
        <div className="w-full max-w-[420px] animate-rise">
          <div className="mb-8 flex items-center gap-2.5">
            <LogoMark size={40} />
            <span className="text-title font-bold tracking-tight text-ink">Outbound</span>
          </div>
          <h1 className="text-title font-semibold text-ink">{title}</h1>
          {subtitle && <p className="mt-1.5 text-body text-muted">{subtitle}</p>}
          <div className="mt-6">{children}</div>
        </div>
      </main>
      <aside className="relative hidden overflow-hidden border-l border-line bg-bg-tint lg:block" aria-hidden>
        <div className="aurora" />
        <div className="grain absolute inset-0" />
        <div className="relative flex h-full flex-col justify-center gap-4 px-16">
          <p className="max-w-[24ch] text-display font-semibold text-ink">The companies, the person, the first email. You approve.</p>
          {[
            ["Find companies that fit your brief", "Discovery looks about four times a day and keeps only the ones that pass."],
            ["Every address checked before it is used", "Catch-all domains wait until they are proven."],
            ["You approve every email", "Approved emails land in your Drafts; you press send."],
          ].map(([head, body], i) => (
            <div key={head} className="glass max-w-md animate-rise rounded-2xl border border-line p-5 shadow-2" style={{ animationDelay: `${150 + i * 120}ms` }}>
              <div className="text-heading font-semibold text-ink">{head}</div>
              <div className="mt-1 text-body text-muted">{body}</div>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}

function Password({ id, label, value, onChange, autoComplete, hint, autoFocus }: { id: string; label: string; value: string; onChange: (value: string) => void; autoComplete: string; hint?: ReactNode; autoFocus?: boolean }) {
  const [shown, setShown] = useState(false);
  // Not a Field: its label wraps the control, and the show button would join the field's name.
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-small font-medium text-ink">
        {label}
      </label>
      <div className="relative">
        <Input id={id} type={shown ? "text" : "password"} autoFocus={autoFocus} autoComplete={autoComplete} value={value} onChange={(e) => onChange(e.target.value)} className="h-9 w-full pr-9" />
        <button type="button" aria-label={shown ? "Hide password" : "Show password"} onClick={() => setShown(!shown)} className="absolute right-2 top-2 text-muted hover:text-ink">
          {shown ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
      {hint && <span className="mt-1 block text-label leading-snug text-muted">{hint}</span>}
    </div>
  );
}

const NEW_PASSWORD_HINT = `At least ${MIN_PASSWORD} characters. A few ordinary words in a row make a good one.`;

// ------------------------------------------------------------------ sign in

function SignIn({ next, email: given }: { next: string | null; email: string }) {
  const [email, setEmail] = useState(given);
  const [password, setPassword] = useState("");
  const signIn = useMutation({
    mutationFn: () => ok(client.POST("/api/auth/login", { body: { email: email.trim(), password } })),
    onSuccess: (me) => go(next ?? landing(me)),
  });
  return (
    <Frame title="Sign in" subtitle="Use the email address your invitation was sent to.">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          signIn.mutate();
        }}
      >
        <Field label="Email">
          <Input id="email" type="email" autoFocus={!given} autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className="h-9 w-full" />
        </Field>
        <Password id="password" label="Password" value={password} onChange={setPassword} autoComplete="current-password" autoFocus={Boolean(given)} />
        <Problem error={signIn.error} />
        <Button type="submit" busy={signIn.isPending} disabled={!email.trim() || !password} className="h-9 w-full">
          Sign in
        </Button>
        <div className="flex items-center justify-between text-[12px]">
          <a href="/forgot-password" className="font-semibold text-primary hover:underline">
            Forgot your password?
          </a>
          <span className="text-muted">
            No account?{" "}
            <a href="https://thehumanfriend.com/#contact" className="font-semibold text-primary hover:underline">
              Ask for an invitation
            </a>
          </span>
        </div>
      </form>
    </Frame>
  );
}

/** After signing in: the workspace used last, else the only one, else the list. */
function landing(me: Me): string {
  const home = homeFor(me);
  return home ? inWorkspace(home) : "/";
}

// ------------------------------------------------------------------ passwords

function ForgotPassword() {
  const [email, setEmail] = useState("");
  const ask = useMutation({ mutationFn: () => ok(client.POST("/api/auth/password/forgot", { body: { email: email.trim() } })) });
  return (
    <Frame title="Reset your password" subtitle="We email you a link that works once, for 30 minutes.">
      {ask.isSuccess ? (
        <Callout tone="good" title="Check your email">
          If {email.trim()} has an account, a reset link is on its way. It can take a minute or two; look in spam as well.
        </Callout>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            ask.mutate();
          }}
        >
          <Field label="Email">
            <Input id="email" type="email" autoFocus autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className="h-9 w-full" />
          </Field>
          <Problem error={ask.error} />
          <Button type="submit" busy={ask.isPending} disabled={!email.includes("@")} className="h-9 w-full">
            Email me a link
          </Button>
        </form>
      )}
      <a href="/sign-in" className="block text-center text-[12px] font-semibold text-primary hover:underline">
        Back to sign in
      </a>
    </Frame>
  );
}

/** For anyone, signed in or not: ask to be taken out of the shared lead directory, then confirm from the emailed link. */
function RemoveMyData({ token }: { token: string }) {
  const [email, setEmail] = useState("");
  const ask = useMutation({ mutationFn: () => ok(client.POST("/api/auth/remove-my-data", { body: { email: email.trim() } })) });
  const confirm = useMutation({ mutationFn: () => ok(client.POST("/api/auth/remove-my-data/confirm", { body: { token } })) });
  if (token)
    return (
      <Frame title="Remove my data" subtitle="Confirm that your details should leave the lead directory.">
        {confirm.isSuccess ? (
          <Callout tone="good" title="Done">
            Your details were removed from the directory and will not be added again.
          </Callout>
        ) : (
          <>
            <p className="text-body text-muted">This removes the address this link was sent to, and any report or note about it, and blocks it from being added again.</p>
            <Problem error={confirm.error} />
            <Button busy={confirm.isPending} onClick={() => confirm.mutate()} className="h-9 w-full">
              Remove my details
            </Button>
          </>
        )}
      </Frame>
    );
  return (
    <Frame title="Remove my data" subtitle="Companies using Outbound share work email addresses they have checked. Ask here to be removed; we email a link to confirm it is you.">
      {ask.isSuccess ? (
        <Callout tone="good" title="Check your email">
          If that address is valid, a confirmation link is on its way. It works once, for a day.
        </Callout>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            ask.mutate();
          }}
        >
          <Field label="Your work email">
            <Input id="email" type="email" autoFocus value={email} onChange={(e) => setEmail(e.target.value)} className="h-9 w-full" />
          </Field>
          <Problem error={ask.error} />
          <Button type="submit" busy={ask.isPending} disabled={!email.includes("@")} className="h-9 w-full">
            Email me a link
          </Button>
        </form>
      )}
    </Frame>
  );
}

function ResetPassword({ token }: { token: string }) {
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const reset = useMutation({
    mutationFn: () => ok(client.POST("/api/auth/password/reset", { body: { token, password } })),
    onSuccess: (me) => go(landing(me)),
  });
  const mismatch = again !== "" && again !== password;
  return (
    <Frame title="Choose a new password" subtitle="This signs you out on every other device.">
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          reset.mutate();
        }}
      >
        <Password id="password" label="New password" value={password} onChange={setPassword} autoComplete="new-password" hint={NEW_PASSWORD_HINT} autoFocus />
        <Password id="again" label="New password again" value={again} onChange={setAgain} autoComplete="new-password" hint={mismatch ? "The two passwords differ." : undefined} />
        <Problem error={reset.error} />
        {reset.error instanceof ApiProblem && reset.error.code === "link_invalid" && (
          <a href="/forgot-password" className="block text-[12px] font-semibold text-primary hover:underline">
            Ask for a new link
          </a>
        )}
        <Button type="submit" busy={reset.isPending} disabled={!token || password.length < MIN_PASSWORD || password !== again} className="h-9 w-full">
          Save and sign in
        </Button>
      </form>
    </Frame>
  );
}

// ------------------------------------------------------------------ invitations

function Invitation({ token }: { token: string }) {
  const invitation = useQuery({ queryKey: ["invitation", token], queryFn: () => ok(client.GET("/api/auth/invitations/{token}", { params: { path: { token } } })) });
  const me = useMe();
  if (invitation.isPending || me.isPending) return <Frame title="Opening your invitation">Loading…</Frame>;
  if (invitation.isError)
    return (
      <Frame title="This invitation cannot be used">
        <Callout tone="attention">It was used already, replaced by a newer one, withdrawn, or is more than 7 days old. Ask the person who invited you to send it again.</Callout>
        <a href="/sign-in" className="block text-center text-[12px] font-semibold text-primary hover:underline">
          Sign in
        </a>
      </Frame>
    );
  const found = invitation.data;
  // No workspace named: an invitation to Outbound itself. They make a workspace or ask to join one next.
  const title = found.workspace_name ? `Join ${found.workspace_name}` : "Welcome to Outbound";
  const subtitle = found.workspace_name
    ? `You are invited as ${found.role === "admin" ? "an admin" : "a member"}.`
    : "Set up your account. Next you can start your own workspace or ask to join your team's.";
  if (!found.has_account) return <NewAccount token={token} email={found.email} title={title} subtitle={subtitle} workspace={found.workspace_name} />;
  const signedInAs = me.data?.user.email;
  return (
    <Frame title={title} subtitle={subtitle}>
      {signedInAs === found.email ? (
        <JoinAsYou token={token} workspace={found.workspace_name} />
      ) : (
        <SignInFirst token={token} email={found.email} signedInAs={signedInAs} />
      )}
    </Frame>
  );
}

/** The workspace someone just joined, by its name among their memberships. */
function joined(me: Me, name: string | null): string {
  if (!name) return "/"; // no workspace yet: `/` offers to make one or ask to join
  const found = me.workspaces.find((w) => w.name === name && w.role);
  if (found) rememberWorkspace(found.slug);
  // A new workspace's admin starts with the guided setup; everyone else on the dashboard.
  return found ? inWorkspace(found.slug, found.role === "admin" ? "/onboarding" : "/") : "/";
}

function NewAccount({ token, email, title, subtitle, workspace }: { token: string; email: string; title: string; subtitle: string; workspace: string | null }) {
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [terms, setTerms] = useState(false);
  const accept = useMutation({
    mutationFn: () => ok(client.POST("/api/auth/invitations/{token}/accept", { params: { path: { token } }, body: { name: name.trim(), password, accept_terms: terms } })),
    onSuccess: (me) => go(joined(me, workspace)),
  });
  return (
    <Frame title={title} subtitle={subtitle}>
      <form
        className="space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          accept.mutate();
        }}
      >
        <div>
          <div className="mb-1 text-small font-medium text-ink">Email</div>
          <div className="text-body font-semibold">{email}</div>
        </div>
        <Field label="Your name">
          <Input id="name" autoFocus autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} className="h-9 w-full" />
        </Field>
        <Password id="password" label="Choose a password" value={password} onChange={setPassword} autoComplete="new-password" hint={NEW_PASSWORD_HINT} />
        <Checkbox label="I accept the Terms of Service and the Acceptable Use Policy" hint="Lawful lists only, and every opt-out is honoured." checked={terms} onChange={setTerms} />
        <Problem error={accept.error} />
        <Button type="submit" busy={accept.isPending} disabled={password.length < MIN_PASSWORD || !terms} className="h-9 w-full">
          Create my account
        </Button>
      </form>
    </Frame>
  );
}

function JoinAsYou({ token, workspace }: { token: string; workspace: string | null }) {
  const accept = useMutation({
    mutationFn: () => ok(client.POST("/api/auth/invitations/{token}/accept", { params: { path: { token } }, body: {} })),
    onSuccess: (me) => go(joined(me, workspace)),
  });
  return (
    <div className="space-y-4">
      <Problem error={accept.error} />
      <Button busy={accept.isPending} onClick={() => accept.mutate()} className="h-9 w-full">
        {workspace ? `Join ${workspace}` : "Continue"}
      </Button>
    </div>
  );
}

function SignInFirst({ token, email, signedInAs }: { token: string; email: string; signedInAs?: string }) {
  const next = `/sign-in?next=${encodeURIComponent(`/invite/${token}`)}&email=${encodeURIComponent(email)}`;
  const signOut = useMutation({ mutationFn: () => client.POST("/api/auth/logout"), onSuccess: () => go(next) });
  return (
    <div className="space-y-4 text-body">
      <p>
        {email} already has an account. {signedInAs ? `You are signed in as ${signedInAs}; sign in as ${email} to accept.` : "Sign in with it to accept."}
      </p>
      {signedInAs ? (
        <Button busy={signOut.isPending} onClick={() => signOut.mutate()} className="h-9 w-full">
          Sign out and continue as {email}
        </Button>
      ) : (
        <Button onClick={() => go(next)} className="h-9 w-full">
          Sign in as {email}
        </Button>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ back from Microsoft or Google

/** The provider sends the browser here with a code (or an error). The workspace is found from
 * the sign-in this session started, so the address needs no workspace in it. */
function OAuthReturn({ params }: { params: URLSearchParams }) {
  const code = params.get("code");
  const state = params.get("state");
  const refused = params.get("error_description") || params.get("error");
  const finish = useMutation({
    mutationFn: () => ok(client.POST("/api/mailboxes/oauth/finish", { body: { code: code ?? "", state: state ?? "" } })),
    onSuccess: ({ slug }) => go(`${inWorkspace(slug)}settings?tab=mailboxes`),
  });
  useEffect(() => {
    if (code && state && !refused) finish.mutate();
    // once: the code can be exchanged a single time
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const back = (
    <a href="/" className="block text-center text-[12px] font-semibold text-primary hover:underline">
      Back to Outbound
    </a>
  );
  if (refused || !code || !state)
    return (
      <Frame title="The mailbox was not connected">
        <Callout tone="attention">{refused ?? "The provider did not send back what we need."} Nothing was saved. Start again from Settings → Mailboxes.</Callout>
        {back}
      </Frame>
    );
  if (finish.isError)
    return (
      <Frame title="The mailbox was not connected">
        <Problem error={finish.error} />
        {back}
      </Frame>
    );
  return <Frame title="Connecting your mailbox">Finishing sign-in…</Frame>;
}

// ------------------------------------------------------------------ `/` and old links

/** Opens the right workspace, or lists them. An old link such as /leads opens in the last one. */
function Home({ path }: { path: string | null }) {
  const me = useMe();
  const home = me.data ? homeFor(me.data) : null;
  useEffect(() => {
    if (me.isError) go(`/sign-in${path ? `?next=${encodeURIComponent(path)}` : ""}`);
    else if (home) go(inWorkspace(home, path ?? "/"));
  }, [me.isError, home, path]);
  if (!me.data || home) return <Frame title="Opening Outbound">Loading…</Frame>;
  return <Workspaces me={me.data} />;
}

function Workspaces({ me }: { me: Me }) {
  const signOut = useMutation({ mutationFn: () => client.POST("/api/auth/logout"), onSuccess: () => go("/sign-in") });
  const staff = me.user.platform_role === "superadmin";
  const none = me.workspaces.length === 0;
  return (
    <Frame title={none ? "Get started" : "Choose a workspace"} subtitle={`Signed in as ${me.user.email}.`}>
      {!none && (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {me.workspaces.map((w) => (
            <li key={w.id}>
              <a href={inWorkspace(w.slug)} onClick={() => w.role && rememberWorkspace(w.slug)} className="flex items-center justify-between gap-3 px-3 py-2.5 text-body hover:bg-surface-2">
                <span className="flex items-center gap-2">
                  <Building2 size={16} className="text-muted" aria-hidden />
                  <span className="font-semibold">{w.name}</span>
                </span>
                <span className="text-label text-muted">{w.role ?? (staff ? "view only" : "")}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
      <GetStarted none={none} askStaff={me.needs_new_workspace ?? false} />
      {me.user.platform_role && (
        <a href="/admin" className="flex h-9 w-full items-center justify-center rounded-lg border border-line-strong text-body font-semibold hover:bg-surface-2">
          Admin console
        </a>
      )}
      <Button variant="secondary" busy={signOut.isPending} onClick={() => signOut.mutate()} className="h-9 w-full">
        Sign out
      </Button>
    </Frame>
  );
}

/** After their workspace was deleted, a person asks the platform team for a new one. */
function AskForWorkspace() {
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [note, setNote] = useState("");
  const asked = useQuery({ queryKey: ["workspace-request"], queryFn: () => ok(client.GET("/api/me/workspace-request")) });
  const ask = useMutation({
    mutationFn: () => ok(client.POST("/api/me/workspace-request", { body: { name: name.trim(), website: website.trim(), note: note.trim() } })),
    onSuccess: () => void asked.refetch(),
  });
  if (asked.data) {
    return <Callout tone="primary">You asked for a new workspace, {asked.data.name}. The platform team will set it up and email you.</Callout>;
  }
  return (
    <form
      className="space-y-2 rounded-lg border border-line p-3"
      onSubmit={(event) => {
        event.preventDefault();
        ask.mutate();
      }}
    >
      <div className="text-body font-semibold">Your workspace was deleted</div>
      <p className="text-label text-muted">Your account is still here. Ask the platform team for a new workspace, and you become its admin.</p>
      <Field label="Company name">
        <Input aria-label="Company name" value={name} onChange={(e) => setName(e.target.value)} className="h-9 w-full" />
      </Field>
      <Field label="Website" hint="Optional.">
        <Input aria-label="Website" value={website} onChange={(e) => setWebsite(e.target.value)} className="h-9 w-full" />
      </Field>
      <Field label="Anything the team should know" hint="Optional.">
        <Input aria-label="Note" value={note} onChange={(e) => setNote(e.target.value)} className="h-9 w-full" />
      </Field>
      <Problem error={ask.error} />
      <Button type="submit" busy={ask.isPending} disabled={!name.trim()} className="h-9 w-full">
        Ask for a new workspace
      </Button>
    </form>
  );
}

/** Make a workspace (and be its admin), or ask to join one with the code its team shares. */
function GetStarted({ none, askStaff }: { none: boolean; askStaff: boolean }) {
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [code, setCode] = useState("");
  const requests = useQuery({
    queryKey: ["join-requests"],
    queryFn: () => ok(client.GET("/api/me/join-requests")),
    refetchInterval: 15000, // an admin may approve while this page is open
  });
  const create = useMutation({
    mutationFn: () => ok(client.POST("/api/me/workspaces", { body: { name: name.trim(), website: website.trim() } })),
    onSuccess: (made) => {
      rememberWorkspace(made.slug);
      go(inWorkspace(made.slug, "/onboarding"));
    },
  });
  const join = useMutation({
    mutationFn: () => ok(client.POST("/api/me/join-requests", { body: { code: code.trim() } })),
    onSuccess: () => {
      setCode("");
      void requests.refetch();
    },
  });
  const waiting = (requests.data ?? []).filter((r) => r.status === "pending");
  const refused = (requests.data ?? []).filter((r) => r.status === "rejected");
  // Approved: the workspace now shows in the person's list, so `/` opens it.
  useEffect(() => {
    if ((requests.data ?? []).some((r) => r.status === "approved") && none) go("/");
  }, [requests.data, none]);
  if (askStaff) {
    return (
      <div className="space-y-4" data-tour="get-started">
        <AskForWorkspace />
      </div>
    );
  }
  return (
    <div className="space-y-4" data-tour="get-started">
      {none && <p className="text-body text-muted">You are not in a workspace yet. Start your own, or ask to join your team's.</p>}
      <form
        className="space-y-2 rounded-lg border border-line p-3"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <div className="text-body font-semibold">Start a workspace</div>
        <Field label="Company name">
          <Input aria-label="Company name" value={name} onChange={(e) => setName(e.target.value)} className="h-9 w-full" />
        </Field>
        <Field label="Website" hint="We read it to draft your profile, so you do not start from a blank page. Optional.">
          <Input aria-label="Website" value={website} onChange={(e) => setWebsite(e.target.value)} className="h-9 w-full" />
        </Field>
        <Problem error={create.error} />
        <Button type="submit" busy={create.isPending} disabled={!name.trim()} className="h-9 w-full">
          Create workspace
        </Button>
        <p className="text-label text-muted">You become its admin and can invite your team and approve requests to join.</p>
      </form>
      <form
        className="space-y-2 rounded-lg border border-line p-3"
        onSubmit={(event) => {
          event.preventDefault();
          join.mutate();
        }}
      >
        <div className="text-body font-semibold">Join a workspace</div>
        <Field label="Join code">
          <Input aria-label="Join code" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Ask a workspace admin for it" className="h-9 w-full" />
        </Field>
        <Problem error={join.error} />
        <Button type="submit" variant="secondary" busy={join.isPending} disabled={!code.trim()} className="h-9 w-full">
          Ask to join
        </Button>
      </form>
      {waiting.map((r) => (
        <Callout key={r.id} tone="primary">
          Waiting for an admin of {r.workspace_name} to approve you. You will see it here and in your notifications.
        </Callout>
      ))}
      {refused.map((r) => (
        <Callout key={r.id} tone="attention">
          {r.workspace_name} did not accept your request.
        </Callout>
      ))}
    </div>
  );
}
