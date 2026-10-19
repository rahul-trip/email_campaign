import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Globe2, Plus, UserX } from "lucide-react";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Callout, Card, Confirm, Empty, Field, Input, PageHeader, Problem, QueryState, SaveNote, Select, Table, Tabs, Td, Textarea, Th } from "../components/ui";
import { cx } from "../lib/cx";
import { when, words } from "../lib/format";

type Policy = Schemas["PolicyOut"];
type Tab = "policies" | "suppressions" | "forget";

const RULES: [Policy["rule"], string][] = [
  ["allow", "Allow"],
  ["allow_with_footer", "Allow with footer"],
  ["consent_required", "Consent required"],
  ["block", "Block"],
];
const RULE_TONE: Record<string, string> = {
  allow: "text-good",
  allow_with_footer: "text-primary",
  consent_required: "text-attention",
  block: "text-error",
};

export function CompliancePage() {
  const [tab, setTab] = useState<Tab>("policies");
  const suppressions = useQuery({ queryKey: ["suppressions"], queryFn: () => ok(client.GET("/api/settings/suppressions")) });
  return (
    <>
      <PageHeader title="Policies and privacy" subtitle="Where cold email is allowed and with what footer, who must never be contacted, and erasure on request." />
      <Tabs
        label="Policies and privacy"
        tour="compliance-tabs"
        value={tab}
        onChange={setTab}
        tabs={[
          [
            "policies",
            <>
              <Globe2 className="size-3.5" aria-hidden /> Country rules
            </>,
          ],
          [
            "suppressions",
            <>
              <Ban className="size-3.5" aria-hidden /> Do not contact{suppressions.data?.length ? ` (${suppressions.data.length})` : ""}
            </>,
          ],
          [
            "forget",
            <>
              <UserX className="size-3.5" aria-hidden /> Forget a person
            </>,
          ],
        ]}
      >
        {tab === "policies" && <Policies />}
        {tab === "suppressions" && <Suppressions />}
        {tab === "forget" && <Forget />}
      </Tabs>
    </>
  );
}

// ------------------------------------------------------------------ country rules

function Policies() {
  const queryClient = useQueryClient();
  const policies = useQuery({ queryKey: ["policies"], queryFn: () => ok(client.GET("/api/settings/policies")) });
  const [code, setCode] = useState("");
  const add = useMutation({
    mutationFn: () => ok(client.PUT("/api/settings/policies/{country_code}", { params: { path: { country_code: code } }, body: { rule: "block" } })),
    onSuccess: () => {
      setCode("");
      void queryClient.invalidateQueries({ queryKey: ["policies"] });
    },
  });
  const exists = (policies.data ?? []).some((p) => p.country_code === code);
  return (
    <Card
      title="Country rules"
      subtitle="Working defaults, not legal advice. Have them reviewed and record who did before automatic sending. A change to the rule, the companies-only box or the footer saves a new version, and each decision records the version it used."
      actions={
        <div className="flex items-center gap-2">
          <Input aria-label="Country code to add" value={code} maxLength={2} onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z]/g, ""))} placeholder="FR" className="w-16 font-mono uppercase" />
          <Button size="sm" variant="secondary" busy={add.isPending} disabled={code.length !== 2 || exists} onClick={() => add.mutate()}>
            <Plus className="size-3.5" aria-hidden /> Add as blocked
          </Button>
        </div>
      }
      className="p-0 [&>header]:px-4 [&>header]:pt-4"
    >
      <Problem error={add.error} className="mx-4 mb-3" />
      <QueryState query={policies}>
        {(rows) =>
          rows.length === 0 ? (
            <Empty>No country rules yet. Countries without a rule are held until one is added.</Empty>
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Country</Th>
                  <Th>Rule</Th>
                  <Th>Footer template</Th>
                  <Th>Reviewed by</Th>
                  <Th>
                    <span className="sr-only">Save</span>
                  </Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <PolicyRow key={`${p.country_code}-${p.version}`} policy={p} />
                ))}
              </tbody>
            </Table>
          )
        }
      </QueryState>
      <p className="px-4 py-3 text-[11px] text-muted">
        Footer fields: <code className="font-mono">{"{sender_legal_name}"}</code>, <code className="font-mono">{"{postal_address}"}</code>, <code className="font-mono">{"{registration_details}"}</code>, <code className="font-mono">{"{contact_info}"}</code> and <code className="font-mono">{"{data_source}"}</code> (where the address came from). Unknown countries are always held.
      </p>
    </Card>
  );
}

function PolicyRow({ policy }: { policy: Policy }) {
  const queryClient = useQueryClient();
  const [rule, setRule] = useState(policy.rule);
  const [corporate, setCorporate] = useState(policy.requires_corporate_subscriber);
  const [footer, setFooter] = useState(policy.footer_template ?? "");
  const [reviewer, setReviewer] = useState(policy.reviewed_by ?? "");
  const ruleChanged = rule !== policy.rule || corporate !== policy.requires_corporate_subscriber || footer !== (policy.footer_template ?? "");
  const changed = ruleChanged || reviewer !== (policy.reviewed_by ?? "");
  const [savedAs, setSavedAs] = useState("Saved.");
  const save = useMutation({
    mutationFn: () =>
      ok(
        client.PUT("/api/settings/policies/{country_code}", {
          params: { path: { country_code: policy.country_code } },
          body: { rule, requires_corporate_subscriber: corporate, allowed_provenance: policy.allowed_provenance, footer_template: footer.trim() || null, reviewed_by: reviewer.trim() || null },
        }),
      ),
    onMutate: () => setSavedAs(ruleChanged ? "Saved as a new version." : "Reviewer saved."),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["policies"] }),
  });
  return (
    <tr className="align-top">
      <Td className="font-mono font-semibold">{policy.country_code}</Td>
      <Td className="min-w-44">
        <Select aria-label={`Rule for ${policy.country_code}`} value={rule} onChange={(e) => setRule(e.target.value as Policy["rule"])} className={cx("font-medium", RULE_TONE[rule])}>
          {RULES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
        <label className="mt-1.5 flex items-center gap-1.5 text-[11px] text-muted">
          <input type="checkbox" checked={corporate} onChange={(e) => setCorporate(e.target.checked)} className="accent-[var(--primary-container)]" /> Incorporated companies only
        </label>
        {policy.allowed_provenance && <div className="mt-1 text-[11px] text-muted">Addresses from: {policy.allowed_provenance.map(words).join(", ")}</div>}
      </Td>
      <Td className="min-w-64">
        <Textarea rows={3} aria-label={`Footer for ${policy.country_code}`} value={footer} onChange={(e) => setFooter(e.target.value)} className="font-mono text-[11px]" placeholder={rule === "block" ? "Not used while blocked" : "Footer text with {fields}"} />
      </Td>
      <Td className="min-w-40">
        <Input aria-label={`Reviewer for ${policy.country_code}`} placeholder="Who checked this?" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        <div className="mt-1 font-mono text-[10px] text-muted">version {policy.version}</div>
      </Td>
      <Td className="whitespace-nowrap">
        <Button size="sm" variant={changed ? "primary" : "secondary"} busy={save.isPending} disabled={!changed} onClick={() => save.mutate()}>
          Save
        </Button>
        <div className="mt-1 max-w-48">
          <SaveNote mutation={save} done={savedAs} />
        </div>
      </Td>
    </tr>
  );
}

// ------------------------------------------------------------------ do not contact

function Suppressions() {
  const queryClient = useQueryClient();
  const entries = useQuery({ queryKey: ["suppressions"], queryFn: () => ok(client.GET("/api/settings/suppressions")) });
  const [kind, setKind] = useState<"email" | "domain">("email");
  const [value, setValue] = useState("");
  const [asking, setAsking] = useState(false);
  const add = useMutation({
    mutationFn: () => ok(client.POST("/api/settings/suppressions", { body: { kind, value: value.trim(), reason: "manual" } })),
    onSuccess: () => {
      setValue("");
      setAsking(false);
      void queryClient.invalidateQueries({ queryKey: ["suppressions"] });
    },
  });
  const valid = kind === "email" ? /.+@.+\..+/.test(value.trim()) : /^[^\s@]+\.[^\s@]+$/.test(value.trim());
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_340px]">
      <Card title="Do not contact" subtitle="Anything on this list is never added and never emailed. Entries cannot be removed." className="p-0 [&>header]:px-4 [&>header]:pt-4">
        <QueryState query={entries}>
          {(rows) =>
            rows.length === 0 ? (
              <Empty>Nobody is on the list yet.</Empty>
            ) : (
              <Table>
                <thead>
                  <tr>
                    <Th>Kind</Th>
                    <Th>Fingerprint</Th>
                    <Th>Reason</Th>
                    <Th>Added</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e.fingerprint + e.kind}>
                      <Td className="text-xs">{e.kind === "email" ? "Address" : "Domain"}</Td>
                      <Td className="font-mono text-[11px]">{e.fingerprint}…</Td>
                      <Td className="text-xs">{words(e.reason)}</Td>
                      <Td className="whitespace-nowrap text-xs text-muted">{when(e.created_at)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )
          }
        </QueryState>
      </Card>
      <Card title="Add to the list" className="h-fit">
        <div className="space-y-3">
          <Field label="Kind">
            <Select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
              <option value="email">One address</option>
              <option value="domain">A whole domain</option>
            </Select>
          </Field>
          <Field label={kind === "email" ? "Address" : "Domain"}>
            <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder={kind === "email" ? "name@company.com" : "company.com"} className="font-mono" />
          </Field>
          <Button busy={add.isPending} disabled={!valid} onClick={() => setAsking(true)}>
            <Ban className="size-3.5" aria-hidden /> Add
          </Button>
          <p className="text-[11px] text-muted">The value is kept only as a one-way fingerprint. A fingerprint of a guessable address can still be tested, so treat the list as sensitive.</p>
        </div>
      </Card>
      {asking && (
        <Confirm title={`Never contact ${value.trim()}?`} confirmLabel="Add to the list" busy={add.isPending} error={add.error} onClose={() => setAsking(false)} onConfirm={() => add.mutate()}>
          <p>It cannot be removed from the list afterwards.</p>
        </Confirm>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ erasure

/** Erase one person on request: suppress the address for good and remove what identifies them. */
function Forget() {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [asking, setAsking] = useState(false);
  const forget = useMutation({
    mutationFn: () => ok(client.POST("/api/privacy/forget", { body: { email: email.trim() } })),
    onSuccess: () => {
      setAsking(false);
      for (const key of ["suppressions", "companies", "lead", "review", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  const result = forget.data;
  return (
    <Card title="Forget a person" subtitle="For someone who asks to be erased." className="max-w-3xl">
      <ul className="mb-4 list-disc space-y-1 pl-4 text-xs text-muted">
        <li>Their address goes on the do-not-contact list for good.</li>
        <li>Their unsent emails are cancelled, and drafts waiting in your mailbox are deleted.</li>
        <li>Their name, title and address are removed from this system. Counts and costs are kept.</li>
      </ul>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Email address" className="min-w-72 flex-1">
          <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="font-mono" />
        </Field>
        <Button variant="danger" disabled={!/.+@.+\..+/.test(email.trim())} onClick={() => setAsking(true)}>
          <UserX className="size-3.5" aria-hidden /> Forget this address…
        </Button>
      </div>
      {result && (
        <Callout tone={result.drafts_left.length ? "attention" : "good"} className="mt-4">
          {result.found ? "Done." : "That address was not in the system, but it is now on the do-not-contact list."} {result.messages_cancelled} unsent email(s) cancelled, {result.drafts_deleted} draft(s) deleted.
          {result.drafts_left.length > 0 && ` The mailbox could not delete ${result.drafts_left.length} draft(s): remove them from the Drafts folder by hand.`}
        </Callout>
      )}
      {asking && (
        <Confirm title={`Erase ${email.trim()}?`} confirmLabel="Forget permanently" busy={forget.isPending} error={forget.error} onClose={() => setAsking(false)} onConfirm={() => forget.mutate()}>
          <p>Everything identifying this person is removed and they are never contacted again. This cannot be undone.</p>
        </Confirm>
      )}
    </Card>
  );
}
