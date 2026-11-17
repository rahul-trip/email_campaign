import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowRight, Download, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { client, ok } from "../api/client";
import { Button, Callout, Card, Checkbox, Field, Input, PageHeader, Problem, QueryState, SaveNote, Skeleton, Tabs, buttonClass } from "../ui/compat";
import { when } from "../lib/format";
import { useOpen, useSetup, SetupList } from "../lib/setup";
import { Mailboxes } from "./Mailboxes";
import { PlanAndUsage } from "./SettingsPlan";
import { Integrations } from "./SettingsIntegrations";
import { Account, Team } from "./SettingsTeam";
import { AboutFields, FooterPreview, LegalFields, SignatureFields, VoiceFields, useSenderProfile, type Profile } from "./SenderProfileParts";
import type { SettingsTab } from "./settingsTabs";

type Tab = SettingsTab;

export function SettingsPage() {
  const { tab = "setup" } = useSearch({ from: "/settings" });
  const navigate = useNavigate();
  const setTab = (next: Tab) => void navigate({ to: "/settings", search: { tab: next === "setup" ? undefined : next }, replace: true });
  return (
    <>
      <PageHeader title="Settings" subtitle="Who you are in every email, the limits the engine works within, and who works here." />
      <Tabs
        label="Settings"
        tour="settings-tabs"
        value={tab}
        onChange={setTab}
        tabs={[
          ["setup", "Setup check"],
          ["profile", "Sender profile"],
          ["mailboxes", "Mailboxes"],
          ["limits", "Limits and budget"],
          ["plan", "Plan and usage"],
          ["team", "Team"],
          ["integrations", "Integrations"],
          ["account", "Your account"],
        ]}
      >
        {tab === "setup" && <Setup />}
        {tab === "profile" && <SenderProfile />}
        {tab === "mailboxes" && <Mailboxes />}
        {tab === "limits" && <Limits />}
        {tab === "plan" && <PlanAndUsage />}
        {tab === "team" && <Team />}
        {tab === "integrations" && <Integrations />}
        {tab === "account" && <Account />}
      </Tabs>
    </>
  );
}

// ------------------------------------------------------------------ setup check

/** What is missing before the engine can work well: the server's list, the same one everywhere. */
function Setup() {
  const setup = useSetup();
  const open = useOpen();
  const missing = setup.data?.items.filter((i) => i.status !== "ok").length ?? 0;
  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card tour="setup-check" title="Setup check" subtitle={!setup.data ? "Checking…" : missing === 0 ? "Everything is in place." : `${missing} of ${setup.data.items.length} need attention.`}>
        {setup.data ? <SetupList items={setup.data.items} onOpen={open} /> : <Skeleton rows={4} />}
        {setup.data && !setup.data.done && (
          <Link to="/onboarding" className={buttonClass("primary", "md", "mt-3")}>Guide me through it</Link>
        )}
      </Card>
      <Card title="Elsewhere" className="h-fit">
        <ul className="space-y-2 text-body">
          {[
            ["/campaigns", "Campaigns", "Job titles, ideal customer, questions"],
            ["/compliance", "Policies and privacy", "Country rules, do not contact, erasure"],
          ].map(([to, title, detail]) => (
            <li key={to}>
              <Link to={to} className="group flex items-center justify-between rounded-lg border border-line px-3 py-2 hover:bg-surface-2">
                <span>
                  <span className="font-medium">{title}</span>
                  <span className="block text-label text-muted">{detail}</span>
                </span>
                <ArrowRight className="size-4 text-muted transition-transform group-hover:translate-x-0.5" aria-hidden />
              </Link>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------ sender profile

export function SenderProfile() {
  const queryClient = useQueryClient();
  const p = useSenderProfile();
  return (
    <QueryState query={p.query} rows={8}>
      {(saved) => {
        const reviewed = (saved as Profile).reviewed_at as string | undefined;
        return (
          <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
            <div className="min-w-0 space-y-5">
              {reviewed ? (
                <Callout tone="good">Confirmed {when(reviewed)}. Saving again confirms it again.</Callout>
              ) : (
                <Callout tone="attention" title="Not confirmed yet">
                  Emails are not written until you have read this profile and saved it. Every statement here ends up in emails under your name, so keep only what is true and can be shown.
                </Callout>
              )}
              <ProfileFile onUploaded={() => { for (const key of ["sender", "status"]) void queryClient.invalidateQueries({ queryKey: [key] }); }} />
              <Card title="1. Legal identity" subtitle="Printed in the footer the law of each country requires.">
                <LegalFields p={p} />
              </Card>
              <Card title="2. Signature" subtitle="Ends every email.">
                <SignatureFields p={p} />
              </Card>
              <Card title="3. What the writer may use" subtitle="The copywriter draws on these. Only true statements.">
                <AboutFields p={p} />
              </Card>
              <Card tour="settings-voice" title="4. How you write" subtitle="How the emails sound and what you want from them.">
                <VoiceFields p={p} />
              </Card>
              <div className="sticky bottom-0 z-10 -mx-1 flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface/95 px-4 py-3 backdrop-blur">
                <Button busy={p.save.isPending} onClick={() => p.save.mutate()}>
                  Confirm and save
                </Button>
                <SaveNote mutation={p.save} done="Saved and confirmed." />
              </div>
            </div>
            <FooterPreview profile={p.draft} />
          </div>
        );
      }}
    </QueryState>
  );
}

// ------------------------------------------------------------------ sender profile file

/** Fill the whole profile from a file: download the empty file, fill it in, upload it back. */
function ProfileFile({ onUploaded }: { onUploaded: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [done, setDone] = useState<string | null>(null);
  const download = useMutation({
    mutationFn: async (current: boolean) => {
      const body = await ok(client.GET("/api/settings/sender-profile/template", { params: { query: { current } } }));
      const blob = new Blob([JSON.stringify(body, null, 2) + "\n"], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = current ? "sender-profile.json" : "sender-profile-template.json";
      link.click();
      URL.revokeObjectURL(link.href);
    },
  });
  const upload = useMutation({
    mutationFn: async (file: File) => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(await file.text());
      } catch {
        throw new Error("That file is not valid JSON. Start from the downloaded template and keep its quotes and commas.");
      }
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) throw new Error("The file must be one JSON object, like the template.");
      return ok(client.PUT("/api/settings/sender-profile", { body: parsed as never }));
    },
    onSuccess: () => {
      setDone("Your profile was filled in from the file and confirmed. Check each part below.");
      onUploaded();
    },
  });
  return (
    <Card tour="profile-file" title="Fill it in from a file" subtitle="Download the file, fill in every value in any editor, and upload it back.">
      <div className="flex flex-wrap items-center gap-2">
        <Button busy={download.isPending && download.variables === false} onClick={() => download.mutate(false)}>
          <Download className="size-3.5" aria-hidden /> Download empty file
        </Button>
        <Button variant="secondary" busy={download.isPending && download.variables === true} onClick={() => download.mutate(true)}>
          Download my current profile
        </Button>
        <Button variant="secondary" busy={upload.isPending} onClick={() => input.current?.click()}>
          <Upload className="size-3.5" aria-hidden /> Upload a file
        </Button>
        <input
          ref={input}
          type="file"
          accept="application/json,.json"
          aria-label="Profile file"
          className="sr-only"
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            setDone(null);
            if (file) upload.mutate(file);
          }}
        />
      </div>
      <p className="mt-2 text-small text-muted">Keep the keys exactly as they are; a file with other keys is refused. Lists (value propositions, technologies, target verticals, case studies, style examples) are lists of text. The greeting is Hi, Hello or Dear. Uploading replaces what is saved and counts as confirming the profile.</p>
      {done && <Callout tone="good" className="mt-3">{done}</Callout>}
      <Problem error={download.error ?? upload.error} className="mt-3" />
    </Card>
  );
}

// ------------------------------------------------------------------ limits

function Limits() {
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const [safe, setSafe] = useState(true);
  const [budget, setBudget] = useState("0.50");
  const [examples, setExamples] = useState(5);
  const [footer, setFooter] = useState(true);
  const [autoCold, setAutoCold] = useState(false);
  const [autoFind, setAutoFind] = useState(true);
  const [perDay, setPerDay] = useState(4);
  const [reviewLimit, setReviewLimit] = useState(50);
  const [minWords, setMinWords] = useState(120);
  const [maxWords, setMaxWords] = useState(200);
  useEffect(() => {
    const s = settings.data;
    if (!s) return;
    setSafe(Boolean(s.safe_to_send_only));
    // No stored ceiling means "no limit", which is a blank box, not zero.
    setBudget(s.budget_per_prospect_micro_usd == null ? "" : (Number(s.budget_per_prospect_micro_usd) / 1_000_000).toFixed(2));
    setExamples(Number(s.few_shot_examples ?? 5));
    setFooter(s.footer_enabled !== false);
    setAutoCold(s.auto_approve_cold === true);
    setAutoFind(s.auto_discovery !== false);
    setPerDay(Number(s.auto_discovery_per_day ?? 4));
    setReviewLimit(Number(s.auto_discovery_review_limit ?? 50));
    setMinWords(Number(s.email_min_words ?? 120));
    setMaxWords(Number(s.email_max_words ?? 200));
  }, [settings.data]);
  const save = useMutation({
    mutationFn: () =>
      ok(
        client.PUT("/api/settings/workspace", {
          body: {
            safe_to_send_only: safe,
            budget_per_prospect_micro_usd: budget.trim() === "" ? null : Math.round(Number(budget) * 1_000_000),
            few_shot_examples: examples,
            footer_enabled: footer,
            auto_approve_cold: autoCold,
            auto_discovery: autoFind,
            auto_discovery_per_day: perDay,
            auto_discovery_review_limit: reviewLimit,
            email_min_words: minWords,
            email_max_words: maxWords,
          },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["workspace-settings"] }),
  });
  const badDiscovery = perDay < 1 || perDay > 6 || reviewLimit < 1 || reviewLimit > 500;
  const badLength = minWords < 40 || maxWords > 600 || minWords > maxWords;
  const badBudget = budget.trim() !== "" && (Number.isNaN(Number(budget)) || Number(budget) < 0);
  return (
    <QueryState query={settings}>
      {() => (
        <Card title="Limits and budget" className="max-w-3xl">
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Budget per prospect (USD)" hint="No paid call is made once a lead has spent this. Blank means no limit; 0 means no paid calls at all.">
              <Input type="number" step="0.01" min="0" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="no limit" />
            </Field>
            <Field label="Shortest first email (words)" hint="The writer is asked for this many at least; the check flags anything shorter. 40 to 600.">
              <Input type="number" min={40} max={600} value={minWords} onChange={(e) => setMinWords(Number(e.target.value))} />
            </Field>
            <Field label="Longest first email (words)" hint="Greeting, sign-off and footer are not counted. 120 to 200 reads like a real note.">
              <Input type="number" min={40} max={600} value={maxWords} onChange={(e) => setMaxWords(Number(e.target.value))} />
            </Field>
            <Field label="Earlier edits shown to the writer" hint="Your last N corrected emails in the campaign teach the writer your style (0 to 20).">
              <Input type="number" min={0} max={20} value={examples} onChange={(e) => setExamples(Number(e.target.value))} />
            </Field>
          </div>
          <div className="mt-4">
            <Checkbox checked={safe} onChange={setSafe} label="Only send to proven addresses (recommended)" hint="Catch-all addresses that could not be proven are held instead of drafted, because they bounce more often." />
          </div>
          <div className="mt-3" data-tour="settings-footer">
            <Checkbox
              checked={footer}
              onChange={setFooter}
              label="Add a footer to every email (recommended)"
              hint="Your company, postal address and a plain way to say no: the country's footer, or a short default where it has none. Kept when a country rule is skipped. The US, UK, EU and Canada expect an address and an opt-out even when no consent is needed."
            />
          </div>
          <div className="mt-4" data-tour="settings-auto-discovery">
            <Checkbox checked={autoFind} onChange={setAutoFind} label="Search for new companies by itself" hint="The worker looks for companies that fit the active campaign and adds the best as leads, using discovery credits." />
            {autoFind && (
              <div className="mt-3 grid gap-4 sm:grid-cols-2">
                <Field label="Searches a day" hint="1 to 6. Four is about every six hours.">
                  <Input type="number" min={1} max={6} value={perDay} onChange={(e) => setPerDay(Number(e.target.value))} />
                </Field>
                <Field label="Stop while Review holds" hint="No search while this many drafts wait for you; it resumes below. 1 to 500.">
                  <Input type="number" min={1} max={500} value={reviewLimit} onChange={(e) => setReviewLimit(Number(e.target.value))} />
                </Field>
              </div>
            )}
          </div>
          <div className="mt-3" data-tour="settings-auto-approve">
            <Checkbox
              checked={autoCold}
              onChange={setAutoCold}
              label="Approve cold leads' emails automatically"
              hint="A lead with a fit score of 80 or lower is cold. With this on, its email skips Review and is saved as a draft in your mailbox on the next pass, even if the writing check flagged it. Hot leads (above 80), leads without a score, and emails that rely on a check you skipped still wait for you. It only saves drafts; nothing is sent."
            />
          </div>
          <p className="mt-4 text-small text-muted">Automatic sending is off and cannot be switched on until the sending phase. Approved emails are saved as drafts.</p>
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-3">
            <Button busy={save.isPending} disabled={badBudget || badLength || badDiscovery} onClick={() => save.mutate()}>
              Save limits
            </Button>
            <SaveNote mutation={save} />
          </div>
        </Card>
      )}
    </QueryState>
  );
}
