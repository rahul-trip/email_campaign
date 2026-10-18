import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Badge, Button, Card, Empty, Field, Input, Problem, Select, Table, Td, Th, Textarea, statusTone, words } from "../components/ui";

type Report = Schemas["IntakeOut"];

function ReportTable({ report }: { report: Report }) {
  return (
    <div className="mt-3">
      {report.validate_only && <p className="mb-1 text-sm text-amber-700">Preview only: nothing has been saved.</p>}
      <Table>
        <thead>
          <tr>
            <Th>Row</Th>
            <Th>Result</Th>
            <Th>Domain</Th>
            <Th>Note</Th>
          </tr>
        </thead>
        <tbody>
          {report.rows.map((row, index) => (
            <tr key={index}>
              <Td>{row.row_number}</Td>
              <Td>
                <Badge tone={statusTone(row.status)}>{words(row.status)}</Badge>
              </Td>
              <Td>{row.domain}</Td>
              <Td className="text-muted">{row.reason}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

function QuickAdd({ campaigns }: { campaigns: Schemas["CampaignOut"][] }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Record<string, string>>({});
  const [validateOnly, setValidateOnly] = useState(false);
  const add = useMutation({
    mutationFn: () => {
      const body: Schemas["TargetIn"] = { validate_only: validateOnly };
      for (const key of ["company", "website", "email", "person", "title", "linkedin", "country", "notes", "campaign_id"] as const) {
        if (form[key]?.trim()) body[key] = form[key].trim();
      }
      if (form.priority) body.priority = Number(form.priority);
      return ok(client.POST("/api/targets", { body }));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["waiting"] });
      void queryClient.invalidateQueries({ queryKey: ["companies"] });
    },
  });
  const set = (key: string) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    add.mutate();
  };
  return (
    <Card title="Add a target">
      <form onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <Field label="Company name">
          <Input value={form.company ?? ""} onChange={set("company")} />
        </Field>
        <Field label="Website or domain">
          <Input value={form.website ?? ""} onChange={set("website")} />
        </Field>
        <Field label="Person">
          <Input value={form.person ?? ""} onChange={set("person")} />
        </Field>
        <Field label="Job title">
          <Input value={form.title ?? ""} onChange={set("title")} />
        </Field>
        <Field label="Known work email">
          <Input value={form.email ?? ""} onChange={set("email")} />
        </Field>
        <Field label="LinkedIn profile URL" hint="Never fetched; used only to find the company.">
          <Input value={form.linkedin ?? ""} onChange={set("linkedin")} />
        </Field>
        <Field label="Country" hint="For example UK or DE">
          <Input value={form.country ?? ""} onChange={set("country")} />
        </Field>
        <Field label="Priority (1 first, 9 last)">
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
        <Field label="Notes for the copywriter">
          <Textarea rows={2} value={form.notes ?? ""} onChange={set("notes")} />
        </Field>
        <div className="flex items-center gap-3 sm:col-span-2">
          <Button type="submit" disabled={add.isPending}>
            {validateOnly ? "Check" : "Add target"}
          </Button>
          <label className="flex items-center gap-1.5 text-sm">
            <input type="checkbox" checked={validateOnly} onChange={(e) => setValidateOnly(e.target.checked)} /> Check only, do not save
          </label>
        </div>
      </form>
      <Problem error={add.error} />
      {add.data && <ReportTable report={add.data} />}
    </Card>
  );
}

function Upload({ campaigns }: { campaigns: Schemas["CampaignOut"][] }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [campaign, setCampaign] = useState("");
  const send = useMutation({
    mutationFn: async (preview: boolean) => {
      const data = new FormData();
      data.append("file", file as File);
      data.append("preview", String(preview));
      if (campaign) data.append("campaign_id", campaign);
      const response = await fetch("/api/targets/upload", { method: "POST", body: data, headers: { "X-Requested-With": "outbound" } });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "Upload failed");
      return { report: body as Report, preview };
    },
    onSuccess: ({ preview }) => {
      if (!preview) {
        void queryClient.invalidateQueries({ queryKey: ["waiting"] });
        void queryClient.invalidateQueries({ queryKey: ["companies"] });
      }
    },
  });
  return (
    <Card title="Upload a CSV or Excel file">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="File">
          <input aria-label="Targets file" type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </Field>
        <Field label="Campaign">
          <Select value={campaign} onChange={(e) => setCampaign(e.target.value)}>
            <option value="">Default</option>
            {campaigns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </Field>
        <Button variant="secondary" disabled={!file || send.isPending} onClick={() => send.mutate(true)}>
          Preview
        </Button>
        <Button disabled={!file || send.isPending || !send.data?.preview} onClick={() => send.mutate(false)}>
          Import after preview
        </Button>
      </div>
      <Problem error={send.error} />
      {send.data && <ReportTable report={send.data.report} />}
    </Card>
  );
}

function Waiting() {
  const queryClient = useQueryClient();
  const rows = useQuery({ queryKey: ["waiting"], queryFn: () => ok(client.GET("/api/targets/waiting")) });
  const [domains, setDomains] = useState<Record<string, string>>({});
  const confirm = useMutation({
    mutationFn: (row: Schemas["WaitingRowOut"]) =>
      ok(client.POST("/api/targets/{row_id}/confirm", { params: { path: { row_id: row.id } }, body: { domain: domains[row.id] || row.resolved_domain || "" } })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["waiting"] });
      void queryClient.invalidateQueries({ queryKey: ["companies"] });
    },
  });
  return (
    <Card title={`Waiting for your confirmation (${rows.data?.length ?? 0})`}>
      {rows.data?.length === 0 && <Empty>Nothing is waiting.</Empty>}
      <ul className="space-y-3">
        {rows.data?.map((row) => (
          <li key={row.id} className="rounded-md border border-line p-3 text-sm">
            <p className="font-medium">{Object.values(row.raw).filter(Boolean).join(" · ")}</p>
            <p className="text-muted">{row.reason}</p>
            <div className="mt-2 flex items-center gap-2">
              <Input
                aria-label="Website for this row"
                placeholder={row.resolved_domain ?? "company website"}
                value={domains[row.id] ?? ""}
                onChange={(e) => setDomains({ ...domains, [row.id]: e.target.value })}
                className="max-w-xs"
              />
              <Button disabled={!(domains[row.id] || row.resolved_domain) || confirm.isPending} onClick={() => confirm.mutate(row)}>
                {domains[row.id] ? "Use this website" : row.resolved_domain ? `Yes, ${row.resolved_domain}` : "Confirm"}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      <Problem error={confirm.error} />
    </Card>
  );
}

export function TargetsPage() {
  const campaigns = useQuery({ queryKey: ["campaigns"], queryFn: () => ok(client.GET("/api/settings/campaigns")) });
  const list = campaigns.data ?? [];
  return (
    <div className="space-y-4">
      <QuickAdd campaigns={list} />
      <Upload campaigns={list} />
      <Waiting />
    </div>
  );
}
