import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../api/client";
import { Button, Callout, Card, Checkbox, Problem, Select } from "./ui";

const FIELDS: [string, string][] = [
  ["email", "The email address"],
  ["still_works", "They no longer work there"],
  ["title", "Their job title"],
  ["linkedin", "Their LinkedIn profile"],
  ["company_name", "The company name"],
  ["country", "The country"],
];

/** What the shared directory knows about this lead's person: a badge, a way to report a wrong detail, and (when allowed) to use the vendors instead. */
export function DirectoryCard({ companyId }: { companyId: string }) {
  const queryClient = useQueryClient();
  const path = { params: { path: { company_id: companyId } } };
  const badge = useQuery({ queryKey: ["directory", companyId], queryFn: () => ok(client.GET("/api/companies/{company_id}/directory", path)) });
  const [field, setField] = useState("email");
  const [open, setOpen] = useState(false);
  const report = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/directory/report", { ...path, body: { field, reason: "" } })),
    onSuccess: () => setOpen(false),
  });
  const skip = useMutation({
    mutationFn: (value: boolean) => ok(client.PUT("/api/companies/{company_id}/directory/skip", { ...path, body: { skip: value } })),
    onSuccess: (data) => queryClient.setQueryData(["directory", companyId], data),
  });
  const data = badge.data;
  if (!data || (!data.in_directory && !data.can_skip)) return null;
  return (
    <Card tour="lead-directory" title="Shared directory" subtitle="Addresses other customers' runs already verified are used first, at no cost.">
      {data.in_directory && (
        <p className="text-xs text-muted">
          This person's address is in the directory, last verified in {data.verified_month}.
        </p>
      )}
      {data.in_directory && !open && !report.isSuccess && (
        <Button size="sm" variant="secondary" className="mt-2" onClick={() => setOpen(true)}>
          Report wrong detail
        </Button>
      )}
      {open && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <Select aria-label="What is wrong" value={field} onChange={(e) => setField(e.target.value)}>
            {FIELDS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
          <Button size="sm" busy={report.isPending} onClick={() => report.mutate()}>
            Send report
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      )}
      {report.isSuccess && (
        <Callout tone="good" className="mt-2">
          Thank you. The directory stops using this address until the team has checked it.
        </Callout>
      )}
      <Problem error={report.error ?? skip.error} className="mt-2" />
      {data.can_skip && (
        <div className="mt-3">
          <Checkbox
            label="Find this lead's email with the vendors instead"
            hint="Costs credits at the vendors; what they find still updates the directory."
            checked={data.skipping}
            onChange={(value) => skip.mutate(value)}
          />
        </div>
      )}
    </Card>
  );
}
