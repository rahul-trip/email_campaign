/** Settings → Mailboxes: connect, check and manage the mailboxes emails are drafted in. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Clock, Mail, Plus, RefreshCw, Star, XCircle } from "lucide-react";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { isViewing, useCurrent } from "../app/session";
import { Button, Callout, Card, Confirm, Dialog, Empty, Field, Input, Problem, QueryState, SaveNote, Select, Textarea } from "../components/ui";
import { cx } from "../lib/cx";
import { ago } from "../lib/format";

type Box = Schemas["MailboxOut"];

const GATEWAY: Record<string, string> = { imap: "IMAP", gmail: "Google", graph: "Microsoft 365", emailengine: "EmailEngine", smartlead: "Smartlead", instantly: "Instantly" };
const STATUS: Record<Box["status"], { label: string; tone: string }> = {
  active: { label: "Working", tone: "text-good" },
  paused: { label: "Paused", tone: "text-muted" },
  error: { label: "Problem", tone: "text-error" },
  needs_reconnect: { label: "Connect again", tone: "text-error" },
};

export function Mailboxes() {
  const { me, workspace } = useCurrent();
  const admin = workspace.role === "admin";
  const viewing = isViewing(workspace);
  const queryClient = useQueryClient();
  const boxes = useQuery({ queryKey: ["mailboxes"], queryFn: () => ok(client.GET("/api/mailboxes")) });
  const options = useQuery({ queryKey: ["mailbox-options"], queryFn: () => ok(client.GET("/api/mailboxes/options")) });
  const [imapOpen, setImapOpen] = useState(false);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["mailboxes"] });
  const gateways = options.data?.gateways ?? ["imap"];

  const oauth = useMutation({
    mutationFn: (gateway: "gmail" | "graph") => ok(client.POST("/api/mailboxes/oauth/start", { body: { gateway } })),
    onSuccess: ({ url }) => window.location.assign(url),
  });

  return (
    <div className="space-y-4" data-tour="mailboxes-panel">
      <Callout tone="info" className="text-[13px]">
        Approved emails are saved as <strong>drafts</strong> in a mailbox you connect here; you read them and press Send in your own mail program. Passwords and sign-in tokens are stored encrypted, and nothing is ever sent without you.
      </Callout>

      {!viewing && (
        <Card tour="mailbox-connect" title="Connect a mailbox" subtitle="Each person can connect their own; an email is drafted in the campaign's mailbox, or the default one.">
          <div className="flex flex-wrap gap-2">
            {gateways.includes("graph") && (
              <Button variant="secondary" busy={oauth.isPending && oauth.variables === "graph"} onClick={() => oauth.mutate("graph")}>
                <Plus className="size-4" aria-hidden /> Microsoft 365 / Outlook
              </Button>
            )}
            {gateways.includes("gmail") && (
              <Button variant="secondary" busy={oauth.isPending && oauth.variables === "gmail"} onClick={() => oauth.mutate("gmail")}>
                <Plus className="size-4" aria-hidden /> Google Workspace / Gmail
              </Button>
            )}
            <Button variant="secondary" onClick={() => setImapOpen(true)}>
              <Plus className="size-4" aria-hidden /> Any other (IMAP)
            </Button>
          </div>
          {!gateways.includes("graph") && !gateways.includes("gmail") && <p className="mt-2 text-xs text-muted">Signing in with Microsoft or Google is not set up on this server yet, so only IMAP is offered.</p>}
          <Problem error={oauth.error} className="mt-3" />
        </Card>
      )}

      {imapOpen && <ImapDialog onClose={() => setImapOpen(false)} onDone={() => { setImapOpen(false); refresh(); }} />}

      <QueryState query={boxes}>
        {(all) =>
          all.length === 0 ? (
            <Card>
              <Empty icon={<Mail className="size-8" />} title="No mailbox connected">
                Connect one above. Until you do, approved emails wait and no draft is saved.
              </Empty>
            </Card>
          ) : (
            all.map((box) => <MailboxCard key={box.id} box={box} mine={box.owner_user_id === me.user.id} admin={admin} viewing={viewing} onChange={refresh} />)
          )
        }
      </QueryState>
    </div>
  );
}

// ------------------------------------------------------------------ one mailbox

function MailboxCard({ box, mine, admin, viewing, onChange }: { box: Box; mine: boolean; admin: boolean; viewing: boolean; onChange: () => void }) {
  const may = !viewing && (admin || (mine && box.owner_user_id !== null));
  const status = STATUS[box.status];
  const [sender, setSender] = useState(false);
  const [removing, setRemoving] = useState(false);
  const path = { params: { path: { mailbox_id: box.id } } };
  const test = useMutation({ mutationFn: () => ok(client.POST("/api/mailboxes/{mailbox_id}/test", path)), onSuccess: onChange });
  const pause = useMutation({ mutationFn: () => ok(client.POST("/api/mailboxes/{mailbox_id}/pause", path)), onSuccess: onChange });
  const resume = useMutation({ mutationFn: () => ok(client.POST("/api/mailboxes/{mailbox_id}/resume", path)), onSuccess: onChange });
  const makeDefault = useMutation({ mutationFn: () => ok(client.POST("/api/mailboxes/{mailbox_id}/default", path)), onSuccess: onChange });
  const remove = useMutation({
    mutationFn: () => client.DELETE("/api/mailboxes/{mailbox_id}", path).then((r) => (r.response.ok ? true : Promise.reject(new Error("Could not disconnect")))),
    onSuccess: () => {
      setRemoving(false);
      onChange();
    },
  });
  const dns = useMutation({ mutationFn: () => ok(client.POST("/api/settings/mailboxes/{mailbox_id}/dns-check", path)), onSuccess: onChange });
  const report = box.dns_check as Record<string, { ok: boolean; detail: string }> | null;
  const person = (box.sender ?? {}) as Record<string, string>;

  return (
    <Card
      title={
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-mono">{box.address}</span>
          {box.is_default && <span className="inline-flex items-center gap-1 rounded-full bg-primary-fixed px-2 py-0.5 text-[11px] font-semibold text-primary"><Star className="size-3" aria-hidden /> Default</span>}
        </span>
      }
      subtitle={
        <>
          {GATEWAY[box.gateway] ?? box.gateway} · <span className={cx("font-semibold", status.tone)}>{status.label}</span>
          {box.last_checked_at && <> · checked {ago(box.last_checked_at)}</>}
          {person.signature_name && <> · signs as {person.signature_name}</>}
        </>
      }
      actions={
        may && (
          <>
            <Button variant="secondary" size="sm" busy={test.isPending} onClick={() => test.mutate()}>
              <RefreshCw className="size-3.5" aria-hidden /> Test
            </Button>
            {box.status === "paused" ? (
              <Button variant="secondary" size="sm" busy={resume.isPending} onClick={() => resume.mutate()}>Resume</Button>
            ) : (
              <Button variant="secondary" size="sm" busy={pause.isPending} onClick={() => pause.mutate()}>Pause</Button>
            )}
            <Button variant="secondary" size="sm" onClick={() => setSender(true)}>Who signs</Button>
            {admin && !box.is_default && <Button variant="secondary" size="sm" busy={makeDefault.isPending} onClick={() => makeDefault.mutate()}>Make default</Button>}
            <Button variant="danger-ghost" size="sm" onClick={() => setRemoving(true)}>Disconnect</Button>
          </>
        )
      }
    >
      {box.status === "needs_reconnect" && (
        <Callout tone="error" icon={<AlertTriangle className="size-4" aria-hidden />} className="mb-3">
          Access to this mailbox has run out or was withdrawn. Approved emails to be drafted here are waiting. Connect the same account again above to continue.
        </Callout>
      )}
      <Problem error={test.error ?? pause.error ?? resume.error ?? makeDefault.error} className="mb-3" />
      {test.data && <p role="status" className={cx("mb-3 text-xs", test.data.ok ? "text-good" : "text-error")}>{test.data.detail}</p>}

      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold text-muted">Email authentication for {box.sending_domain}</span>
        {may && (
          <Button variant="ghost" size="sm" busy={dns.isPending} onClick={() => dns.mutate()}>
            <RefreshCw className="size-3.5" aria-hidden /> {report ? "Check DNS again" : "Check DNS"}
          </Button>
        )}
      </div>
      <Problem error={dns.error} className="mb-2" />
      {report ? (
        <div className={cx("grid gap-3", report.mx ? "md:grid-cols-4" : "md:grid-cols-3")}>
          {(["mx", "spf", "dkim", "dmarc"] as const).filter((key) => report[key]).map((key) => {
            const record = report[key];
            return (
              <div key={key} className={cx("rounded-lg border p-3 text-xs", record?.ok ? "border-line bg-surface-low" : "border-error/30 bg-error-container/50")}>
                <div className="flex items-center justify-between">
                  <span className="font-mono font-semibold uppercase">{key}</span>
                  <span className={cx("inline-flex items-center gap-1 font-semibold", record?.ok ? "text-good" : "text-error")}>
                    {record?.ok ? <CheckCircle2 className="size-3.5" aria-hidden /> : <XCircle className="size-3.5" aria-hidden />}
                    {record?.ok ? "Set up" : "Problem"}
                  </span>
                </div>
                <p className="mt-1.5 break-words font-mono text-[11px] text-muted">{record?.detail || "No details reported."}</p>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="flex items-center gap-2 text-xs text-muted">
          <Clock className="size-3.5" aria-hidden /> DNS has not been checked yet.
        </p>
      )}

      {sender && <SenderDialog box={box} onClose={() => setSender(false)} onDone={() => { setSender(false); onChange(); }} />}
      {removing && (
        <Confirm title={`Disconnect ${box.address}?`} confirmLabel="Disconnect" busy={remove.isPending} error={remove.error} onClose={() => setRemoving(false)} onConfirm={() => remove.mutate()}>
          Its stored password or sign-in is deleted{box.gateway === "gmail" ? " and Google is told to withdraw access" : ""}. Drafts already saved stay in the mailbox. Campaigns that sent from it use the default mailbox instead.
        </Confirm>
      )}
    </Card>
  );
}

// ------------------------------------------------------------------ dialogs

function ImapDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [address, setAddress] = useState("");
  const [host, setHost] = useState("");
  const [port, setPort] = useState<993 | 143>(993);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const connect = useMutation({
    mutationFn: () => ok(client.POST("/api/mailboxes/imap", { body: { address: address.trim(), host: host.trim(), port, username: username.trim() || null, password } })),
    onSuccess: onDone,
  });
  return (
    <Dialog
      title="Connect an IMAP mailbox"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button busy={connect.isPending} disabled={!address.includes("@") || !host.trim() || !password} onClick={() => connect.mutate()}>Test and connect</Button>
        </>
      }
    >
      <p className="text-xs text-muted">Use an <strong>app password</strong> if your provider offers one. We sign in once to check the login and find the Drafts and Sent folders before saving anything.</p>
      <Field label="Email address">
        <Input type="email" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="you@yourcompany.com" autoFocus className="w-full" />
      </Field>
      <div className="grid grid-cols-3 gap-3">
        <Field label="IMAP server" className="col-span-2">
          <Input value={host} onChange={(e) => setHost(e.target.value)} placeholder="imap.yourcompany.com" className="w-full" />
        </Field>
        <Field label="Port" hint={port === 993 ? "Encrypted" : "Upgraded to encrypted"}>
          <Select value={port} onChange={(e) => setPort(Number(e.target.value) as 993 | 143)}>
            <option value={993}>993</option>
            <option value={143}>143</option>
          </Select>
        </Field>
      </div>
      <Field label="User name" hint="Leave empty if it is the email address.">
        <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" className="w-full" />
      </Field>
      <Field label="App password">
        <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" className="w-full" />
      </Field>
      <Problem error={connect.error} />
    </Dialog>
  );
}

function SenderDialog({ box, onClose, onDone }: { box: Box; onClose: () => void; onDone: () => void }) {
  const start = (box.sender ?? {}) as Record<string, unknown>;
  const [name, setName] = useState(String(start.signature_name ?? ""));
  const [title, setTitle] = useState(String(start.signature_title ?? ""));
  const [greeting, setGreeting] = useState(String(start.greeting ?? ""));
  const [examples, setExamples] = useState(((start.style_examples as string[] | undefined) ?? []).join("\n---\n"));
  const save = useMutation({
    mutationFn: () =>
      ok(
        client.PUT("/api/mailboxes/{mailbox_id}/sender", {
          params: { path: { mailbox_id: box.id } },
          body: { signature_name: name.trim(), signature_title: title.trim(), greeting: greeting as "" | "Hi" | "Hello" | "Dear", style_examples: examples.split("\n---\n").map((e) => e.trim()).filter(Boolean).slice(0, 4) },
        }),
      ),
    onSuccess: onDone,
  });
  return (
    <Dialog
      title={`Who signs from ${box.address}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button busy={save.isPending} onClick={() => save.mutate()}>Save</Button>
        </>
      }
    >
      <p className="text-xs text-muted">Emails drafted in this mailbox are signed by this person. Anything left empty uses the company profile in Settings → Sender profile.</p>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Sam Lee" autoFocus className="w-full" />
        </Field>
        <Field label="Title">
          <Input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="CPO, Quantra" className="w-full" />
        </Field>
      </div>
      <Field label="Greeting">
        <Select value={greeting} onChange={(e) => setGreeting(e.target.value)}>
          <option value="">Company default</option>
          <option value="Hi">Hi</option>
          <option value="Hello">Hello</option>
          <option value="Dear">Dear</option>
        </Select>
      </Field>
      <Field label="Emails in this person's voice" hint="Up to four past emails, separated by a line with ---. Read for tone, never copied.">
        <Textarea rows={5} value={examples} onChange={(e) => setExamples(e.target.value)} className="w-full" />
      </Field>
      <Problem error={save.error} />
      <SaveNote mutation={save} />
    </Dialog>
  );
}
