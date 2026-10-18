import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { client, ok } from "../../api/client";
import { Button, Card, Field, Input, Problem } from "../../components/ui";
import { useSave } from "./shared";

export function Limits() {
  const settings = useQuery({ queryKey: ["workspace-settings"], queryFn: () => ok(client.GET("/api/settings/workspace")) });
  const [safe, setSafe] = useState(true);
  const [budget, setBudget] = useState("0.50");
  const [examples, setExamples] = useState(5);
  useEffect(() => {
    const s = settings.data;
    if (!s) return;
    setSafe(Boolean(s.safe_to_send_only));
    // No stored ceiling means "no limit", which is a blank box, not zero.
    setBudget(s.budget_per_prospect_micro_usd == null ? "" : (Number(s.budget_per_prospect_micro_usd) / 1_000_000).toFixed(2));
    setExamples(Number(s.few_shot_examples ?? 5));
  }, [settings.data]);
  const save = useSave("workspace-settings", () =>
    ok(
      client.PUT("/api/settings/workspace", {
        body: { safe_to_send_only: safe, budget_per_prospect_micro_usd: budget.trim() === "" ? null : Math.round(Number(budget) * 1_000_000), few_shot_examples: examples },
      }),
    ),
  );
  return (
    <Card title="Limits" actions={<Button onClick={() => save.mutate(undefined)}>Save</Button>}>
      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Budget per prospect (USD)" hint="No paid call is made once a lead has spent this. Leave blank for no limit; 0 means no paid calls at all.">
          <Input type="number" step="0.01" min="0" value={budget} onChange={(e) => setBudget(e.target.value)} />
        </Field>
        <Field label="Earlier edits shown to the writer" hint="Your last N corrected emails in the campaign.">
          <Input type="number" min={0} max={20} value={examples} onChange={(e) => setExamples(Number(e.target.value))} />
        </Field>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" checked={safe} onChange={(e) => setSafe(e.target.checked)} />
          <span>
            <strong>Only send to proven addresses</strong>
            <span className="block text-xs text-muted">Catch-all addresses that could not be proven are held.</span>
          </span>
        </label>
      </div>
      <p className="mt-3 text-xs text-muted">Automatic sending is off, and cannot be switched on until the later send phase.</p>
      <Problem error={save.error} />
      {save.isSuccess && <p className="mt-2 text-sm text-green-700">Saved.</p>}
    </Card>
  );
}
