import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileSpreadsheet, Info, Plus, Upload } from "lucide-react";
import { useState } from "react";
import { asUpload, client, multipart, ok, type Schemas } from "../api/client";
import { StatusBadge } from "../components/StatusBadge";
import { Button, Callout, Card, Checkbox, Empty, Field, Input, PageHeader, Problem, QueryState, Select, Table, Tabs, Td, Textarea, Th } from "../components/ui";
import { describe, importRowStatus } from "../lib/status";
import { ConfirmRow } from "./Attention";

type Report = Schemas["IntakeOut"];
type Tab = "add" | "upload" | "confirm";

export function TargetsPage() {
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  const waiting = useQuery({ queryKey: ["waiting"], queryFn: () => ok(client.GET("/api/targets/waiting")) });
  const [tab, setTab] = useState<Tab>("add");
  const list = campaigns.data ?? [];
  return (
    <>
      <PageHeader title="Add leads" subtitle="One company at a time from whatever you know, or a whole spreadsheet. The next run researches them." />
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0">
          <Tabs
            label="Ways to add leads"
            tour="target-tabs"
            value={tab}
            onChange={setTab}
            tabs={[
              ["add", "Add one company"],
              ["upload", "Upload a file"],
              ["confirm", `Websites to confirm${waiting.data?.length ? ` (${waiting.data.length})` : ""}`],
            ]}
          >
            {tab === "add" && <QuickAdd campaigns={list} />}
            {tab === "upload" && <UploadFile campaigns={list} />}
            {tab === "confirm" && (
              <Card title="Websites to confirm" subtitle="Added by name, and the website found is not certain (below 80% sure). Confirm it or give the right one.">
                <QueryState query={waiting}>
                  {(rows) =>
                    rows.length === 0 ? (
                      <Empty icon={<CheckCircle2 className="size-7 text-good" />}>Nothing is waiting for confirmation.</Empty>
                    ) : (
                      <ul className="divide-y divide-line">
                        {rows.map((row) => (
                          <ConfirmRow key={row.id} row={row} />
                        ))}
                      </ul>
                    )
                  }
                </QueryState>
              </Card>
            )}
          </Tabs>
        </div>
        <Card title="What happens to each row" className="h-fit">
          <ul className="space-y-2.5 text-xs text-muted">
            <li>
              <strong className="text-ink">One piece is enough:</strong> a website, a company name, a work email, a person and company, or a LinkedIn profile URL.
            </li>
            <li>
              <strong className="text-ink">A name only</strong> costs one web search to find the website; if it is not sure, it asks you.
            </li>
            <li>
              <strong className="text-ink">The same website</strong> is never added twice: your notes are added to the existing lead.
            </li>
            <li>
              <strong className="text-ink">The do-not-contact list</strong> always wins: those rows are refused.
            </li>
            <li>
              <strong className="text-ink">What you type</strong> (name, country, priority) is marked as yours and never overwritten.
            </li>
            <li>
              <strong className="text-ink">LinkedIn profiles</strong> are never opened; a public search on the profile finds the person and company.
            </li>
          </ul>
        </Card>
      </div>
    </>
  );
}

function ReportTable({ report }: { report: Report }) {
  const counts = report.rows.reduce<Record<string, number>>((acc, row) => ({ ...acc, [row.status]: (acc[row.status] ?? 0) + 1 }), {});
  return (
    <div className="mt-4 space-y-2">
      {report.validate_only && (
        <Callout tone="info" icon={<Info className="size-4" />}>
          Preview only: nothing has been saved.
        </Callout>
      )}
      <div className="flex flex-wrap gap-2">
        {Object.entries(counts).map(([status, n]) => (
          <span key={status} className="inline-flex items-center gap-1.5">
            <StatusBadge status={describe(importRowStatus, status)} />
            <span className="font-mono text-xs">{n}</span>
          </span>
        ))}
      </div>
      <Table className="rounded-lg border border-line">
        <thead>
          <tr>
            <Th>Row</Th>
            <Th>Result</Th>
            <Th>Website</Th>
            <Th>Note</Th>
          </tr>
        </thead>
        <tbody>
          {report.rows.map((row, i) => (
            <tr key={i}>
              <Td className="font-mono text-xs text-muted">{row.row_number ?? i + 1}</Td>
              <Td>
                <StatusBadge status={describe(importRowStatus, row.status)} />
              </Td>
              <Td className="font-mono text-xs">{row.domain ?? "–"}</Td>
              <Td className="text-xs text-muted">{row.reason}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

const FIELDS = ["company", "website", "email", "person", "title", "linkedin", "country", "notes", "campaign_id"] as const;

function QuickAdd({ campaigns }: { campaigns: Schemas["CampaignOut"][] }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Record<string, string>>({});
  const [checkOnly, setCheckOnly] = useState(false);
  const add = useMutation({
    mutationFn: () => {
      const body: Schemas["TargetIn"] = { validate_only: checkOnly };
      for (const key of FIELDS) if (form[key]?.trim()) body[key] = form[key].trim();
      if (form.priority) body.priority = Number(form.priority);
      return ok(client.POST("/api/targets", { body }));
    },
    onSuccess: (report) => {
      if (report.validate_only) return;
      setForm({});
      for (const key of ["waiting", "companies", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  const set = (key: string) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const anchor = ["company", "website", "email", "linkedin"].some((key) => form[key]?.trim());
  const submit = (event: { preventDefault: () => void }) => {
    event.preventDefault();
    add.mutate();
  };
  return (
    <Card tour="add-target" title="Add one company" subtitle="Fill in whatever you know; one of the first four is enough.">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <Field label="Website or domain">
          <Input value={form.website ?? ""} onChange={set("website")} placeholder="acme.com" />
        </Field>
        <Field label="Company name">
          <Input value={form.company ?? ""} onChange={set("company")} placeholder="Acme Energy" />
        </Field>
        <Field label="Known work email" hint="The address is still verified before use.">
          <Input type="email" value={form.email ?? ""} onChange={set("email")} />
        </Field>
        <Field label="LinkedIn profile URL" hint="Never opened; used only to find the person and company.">
          <Input value={form.linkedin ?? ""} onChange={set("linkedin")} />
        </Field>
        <Field label="Person" hint="They are tried first when the email is written.">
          <Input value={form.person ?? ""} onChange={set("person")} placeholder="First and last name" />
        </Field>
        <Field label="Job title">
          <Input value={form.title ?? ""} onChange={set("title")} />
        </Field>
        <Field label="Country" hint="For example GB, US or Germany. Leave blank to have it worked out.">
          <Input value={form.country ?? ""} onChange={set("country")} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Priority" hint="1 first, 9 last">
            <Input type="number" min={1} max={9} value={form.priority ?? ""} onChange={set("priority")} />
          </Field>
          <Field label="Campaign">
            <Select value={form.campaign_id ?? ""} onChange={set("campaign_id")}>
              <option value="">Default</option>
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <Field label="Notes for the copywriter" hint={'Read by the writer and the fit check, for example "met at the expo".'} className="sm:col-span-2">
          <Textarea rows={2} value={form.notes ?? ""} onChange={set("notes")} />
        </Field>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3 sm:col-span-2">
          <Checkbox checked={checkOnly} onChange={setCheckOnly} label="Check only, do not save" />
          <Button type="submit" busy={add.isPending} disabled={!anchor}>
            <Plus className="size-4" aria-hidden /> {checkOnly ? "Check" : "Add company"}
          </Button>
        </div>
      </form>
      <Problem error={add.error} className="mt-3" />
      {add.data && <ReportTable report={add.data} />}
    </Card>
  );
}

function UploadFile({ campaigns }: { campaigns: Schemas["CampaignOut"][] }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [campaign, setCampaign] = useState("");
  const send = useMutation({
    mutationFn: async (preview: boolean) => {
      const report = await ok(
        client.POST("/api/targets/upload", {
          body: { file: asUpload(file as File), preview, campaign_id: campaign || undefined },
          bodySerializer: multipart,
        }),
      );
      return { report, preview, name: file?.name };
    },
    onSuccess: ({ preview }) => {
      if (preview) return;
      for (const key of ["waiting", "companies", "status"]) void queryClient.invalidateQueries({ queryKey: [key] });
    },
  });
  const previewed = send.data?.preview && send.data.name === file?.name;
  return (
    <Card title="Upload a CSV or Excel file" subtitle="Columns are matched loosely: Company, Website, Email, Person, Title, LinkedIn, Country, Notes, Priority. Up to 2 MB.">
      <label className="flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-outline bg-surface-low px-4 py-8 text-center transition-colors hover:border-primary-container">
        <FileSpreadsheet className="size-9 text-muted" aria-hidden />
        <span className="mt-2 text-[13px] font-semibold">{file ? file.name : "Choose a .csv or .xlsx file"}</span>
        <span className="mt-0.5 text-xs text-muted">{file ? `${Math.ceil(file.size / 1024)} KB` : "Nothing is saved until you import after the preview."}</span>
        <input
          aria-label="Targets file"
          type="file"
          accept=".csv,.xlsx"
          className="sr-only"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            send.reset();
          }}
        />
      </label>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <Field label="Campaign" className="min-w-48">
          <Select value={campaign} onChange={(e) => setCampaign(e.target.value)}>
            <option value="">Default</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <Button variant="secondary" busy={send.isPending && send.variables === true} disabled={!file} onClick={() => send.mutate(true)}>
          1. Preview
        </Button>
        <Button busy={send.isPending && send.variables === false} disabled={!file || !previewed} onClick={() => send.mutate(false)}>
          <Upload className="size-4" aria-hidden /> 2. Import
        </Button>
      </div>
      <Problem error={send.error} className="mt-3" />
      {send.data && !send.data.preview && (
        <Callout tone="good" className="mt-4">
          Imported. The next run researches the accepted rows.
        </Callout>
      )}
      {send.data && <ReportTable report={send.data.report} />}
    </Card>
  );
}
