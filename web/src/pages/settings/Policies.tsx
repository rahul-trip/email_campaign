import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../../api/client";
import { Button, Card, Field, Input, Problem, SaveNote, Select, Table, Td, Th, Textarea, words } from "../../components/ui";
import { useSave } from "./shared";

const RULES = ["allow", "allow_with_footer", "consent_required", "block"] as const;

function PolicyRow({ policy }: { policy: Schemas["PolicyOut"] }) {
  const [rule, setRule] = useState<(typeof RULES)[number]>(policy.rule);
  const [corporate, setCorporate] = useState(policy.requires_corporate_subscriber);
  const [footer, setFooter] = useState(policy.footer_template ?? "");
  const [reviewer, setReviewer] = useState(policy.reviewed_by ?? "");
  const save = useSave("policies", () =>
    ok(
      client.PUT("/api/settings/policies/{country_code}", {
        params: { path: { country_code: policy.country_code } },
        body: { rule, requires_corporate_subscriber: corporate, allowed_provenance: policy.allowed_provenance, footer_template: footer || null, reviewed_by: reviewer || null },
      }),
    ),
  );
  return (
    <tr>
      <Td className="font-semibold">{policy.country_code}</Td>
      <Td>
        <Select aria-label={`Rule for ${policy.country_code}`} value={rule} onChange={(e) => setRule(e.target.value as typeof rule)}>
          {RULES.map((r) => (
            <option key={r} value={r}>
              {words(r)}
            </option>
          ))}
        </Select>
        <label className="mt-1 flex items-center gap-1 text-xs">
          <input type="checkbox" checked={corporate} onChange={(e) => setCorporate(e.target.checked)} /> companies only
        </label>
      </Td>
      <Td>
        <Textarea rows={3} aria-label={`Footer for ${policy.country_code}`} value={footer} onChange={(e) => setFooter(e.target.value)} />
      </Td>
      <Td>
        <Input aria-label={`Reviewer for ${policy.country_code}`} placeholder="Who checked this?" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
        <span className="text-xs text-muted">v{policy.version}</span>
      </Td>
      <Td>
        <Button variant="secondary" onClick={() => save.mutate(undefined)}>
          Save
        </Button>
        <SaveNote mutation={save} done="Saved as a new version." />
      </Td>
    </tr>
  );
}

export function Policies() {
  const policies = useQuery({ queryKey: ["policies"], queryFn: () => ok(client.GET("/api/settings/policies")) });
  const [code, setCode] = useState("");
  const add = useSave("policies", () =>
    ok(client.PUT("/api/settings/policies/{country_code}", { params: { path: { country_code: code } }, body: { rule: "block" } })),
  );
  return (
    <Card title="Country policies">
      <p className="mb-3 text-sm text-muted">
        These are working defaults, not legal advice. Have them reviewed, and record who did, before turning on automatic sending. Every change raises the version, and each decision records the version it used.
      </p>
      <Table>
        <thead>
          <tr>
            <Th>Country</Th>
            <Th>Rule</Th>
            <Th>Footer</Th>
            <Th>Review</Th>
            <Th />
          </tr>
        </thead>
        <tbody>
          {policies.data?.map((p) => (
            <PolicyRow key={p.country_code} policy={p} />
          ))}
        </tbody>
      </Table>
      <div className="mt-3 flex items-end gap-2">
        <Field label="Add a country (two letters)">
          <Input value={code} maxLength={2} onChange={(e) => setCode(e.target.value.toUpperCase())} className="w-24" />
        </Field>
        <Button variant="secondary" disabled={code.length !== 2} onClick={() => add.mutate(undefined)}>
          Add as blocked
        </Button>
      </div>
      <Problem error={add.error} />
    </Card>
  );
}
