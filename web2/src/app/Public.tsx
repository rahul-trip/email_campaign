/**
 * The pages outside a workspace: signing in, a forgotten password, an invitation, and `/`, which
 * opens the right workspace. They are few and plain, so they are picked by path here instead of
 * by the workspace router, and each one leaves with a full page load.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Building2, Eye, EyeOff, Zap } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { ApiProblem, client, ok } from "../api/client";
import { Button, Callout, Checkbox, Field, Input, Problem } from "../components/ui";
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
  if (pathname === "/reset-password") return <ResetPassword token={params.get("token") ?? ""} />;
  if (pathname === "/oauth/callback") return <OAuthReturn params={params} />;
  const invite = pathname.match(/^\/invite\/([^/]+)\/?$/);
  if (invite) return <Invitation token={decodeURIComponent(invite[1]!)} />;
  return <Home path={pathname === "/" ? null : pathname + search} />;
}

// ------------------------------------------------------------------ frame

function Frame({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  useEffect(() => {
    document.title = `${title} · Outbound`;
  }, [title]);
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-4 py-8">
      <div className="w-full max-w-sm space-y-5 rounded-xl border border-line bg-surface p-7 shadow-sm">
        <div className="flex items-center gap-2">
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-on-primary">
            <Zap size={18} aria-hidden />
          </span>
          <span className="text-xl font-bold tracking-tight">Outbound</span>
        </div>
        <div>
          <h1 className="text-lg font-semibold">{title}</h1>
          {subtitle && <p className="text-xs text-muted">{subtitle}</p>}
        </div>
        {children}
      </div>
    </main>
  );
}

function Password({ id, label, value, onChange, autoComplete, hint, autoFocus }: { id: string; label: string; value: string; onChange: (value: string) => void; autoComplete: string; hint?: ReactNode; autoFocus?: boolean }) {
  const [shown, setShown] = useState(false);
  // Not a Field: its label wraps the control, and the show button would join the field's name.
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-medium text-ink">
        {label}
      </label>
      <div className="relative">
        <Input id={id} type={shown ? "text" : "password"} autoFocus={autoFocus} autoComplete={autoComplete} value={value} onChange={(e) => onChange(e.target.value)} className="h-9 w-full pr-9" />
        <button type="button" aria-label={shown ? "Hide password" : "Show password"} onClick={() => setShown(!shown)} className="absolute right-2 top-2 text-muted hover:text-ink">
          {shown ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
      {hint && <span className="mt-1 block text-[11px] leading-snug text-muted">{hint}</span>}
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
          <span className="text-muted">No account? Ask for an invitation.</span>
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
  const title = `Join ${found.workspace_name}`;
  const subtitle = `You are invited as ${found.role === "admin" ? "an admin" : "a member"}.`;
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
function joined(me: Me, name: string): string {
  const found = me.workspaces.find((w) => w.name === name && w.role);
  if (found) rememberWorkspace(found.slug);
  // A new workspace's admin starts with the guided setup; everyone else on the dashboard.
  return found ? inWorkspace(found.slug, found.role === "admin" ? "/onboarding" : "/") : "/";
}

function NewAccount({ token, email, title, subtitle, workspace }: { token: string; email: string; title: string; subtitle: string; workspace: string }) {
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
          <div className="mb-1 text-xs font-medium text-ink">Email</div>
          <div className="text-[13px] font-semibold">{email}</div>
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

function JoinAsYou({ token, workspace }: { token: string; workspace: string }) {
  const accept = useMutation({
    mutationFn: () => ok(client.POST("/api/auth/invitations/{token}/accept", { params: { path: { token } }, body: {} })),
    onSuccess: (me) => go(joined(me, workspace)),
  });
  return (
    <div className="space-y-4">
      <Problem error={accept.error} />
      <Button busy={accept.isPending} onClick={() => accept.mutate()} className="h-9 w-full">
        Join {workspace}
      </Button>
    </div>
  );
}

function SignInFirst({ token, email, signedInAs }: { token: string; email: string; signedInAs?: string }) {
  const next = `/sign-in?next=${encodeURIComponent(`/invite/${token}`)}&email=${encodeURIComponent(email)}`;
  const signOut = useMutation({ mutationFn: () => client.POST("/api/auth/logout"), onSuccess: () => go(next) });
  return (
    <div className="space-y-4 text-[13px]">
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
  return (
    <Frame title="Choose a workspace" subtitle={`Signed in as ${me.user.email}.`}>
      {me.workspaces.length === 0 ? (
        <Callout tone="attention">You are not in any workspace yet. Ask an admin for an invitation.</Callout>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {me.workspaces.map((w) => (
            <li key={w.id}>
              <a href={inWorkspace(w.slug)} onClick={() => w.role && rememberWorkspace(w.slug)} className="flex items-center justify-between gap-3 px-3 py-2.5 text-[13px] hover:bg-surface-low">
                <span className="flex items-center gap-2">
                  <Building2 size={16} className="text-muted" aria-hidden />
                  <span className="font-semibold">{w.name}</span>
                </span>
                <span className="text-[11px] text-muted">{w.role ?? (staff ? "view only" : "")}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
      <Button variant="secondary" busy={signOut.isPending} onClick={() => signOut.mutate()} className="h-9 w-full">
        Sign out
      </Button>
    </Frame>
  );
}
