/**
 * Find more people at one lead, or at several: pick the roles (recruiters, a head of engineering,
 * the founders again, or your own words) and what to do with who is found. Nothing runs by itself:
 * a search uses a few AI credits per lead, and what is done for each person is the reader's choice.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Callout, Dialog, Field, Input, Problem } from "./compat";
import { Chip } from "./core";
import { cx } from "../lib/cx";

type Reach = Schemas["FindPeopleIn"]["reach"];
type Person = Schemas["ReachedPersonOut"];
export type FindTarget = { id: string; name: string };

const PRESETS = ["Founder", "Co-founder", "CEO", "CTO", "Head of Engineering", "Recruiter", "Head of Talent", "Head of Sales"];
const MAX_ROLES = 4;

const REACH: [Reach, string, string][] = [
  ["none", "Just add them", "They are listed on the lead. You choose later what to do for each."],
  ["email", "Find their email", "A run looks for each confirmed person's address with the usual finders and checks."],
  ["linkedin", "Write a LinkedIn message", "A connection note and a first message for each confirmed person with a profile."],
  ["both", "Both", "Their email, and a LinkedIn message."],
];

/** What happened for one person, in a few plain words. */
function outcome(p: Person): string[] {
  if (!p.confirmed) return p.email || p.linkedin ? ["confirm they work here first"] : ["not placed at the company yet: confirm them on the lead"];
  const lines: string[] = [];
  if (p.email) lines.push(p.email === "asked" ? "looking for their email" : `email: ${p.email}`);
  if (p.linkedin) lines.push(p.linkedin === "written" ? "LinkedIn message written" : `LinkedIn: ${p.linkedin}`);
  return lines;
}

function People({ people }: { people: Person[] }) {
  if (people.length === 0) return <p className="text-small text-muted">Nobody new.</p>;
  return (
    <ul className="divide-y divide-line text-body">
      {people.map((p) => (
        <li key={p.contact_id} className="py-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">{p.name}</span>
            {p.title && <span className="text-muted">{p.title}</span>}
            {!p.confirmed && <Chip tone="attention">To confirm</Chip>}
          </div>
          {outcome(p).map((line) => (
            <div key={line} className="text-small text-muted">
              {line}
            </div>
          ))}
        </li>
      ))}
    </ul>
  );
}

export function FindPeopleDialog({ targets, onClose, onDone }: { targets: FindTarget[]; onClose: () => void; onDone: () => void }) {
  const queryClient = useQueryClient();
  const [roles, setRoles] = useState<string[]>([]);
  const [custom, setCustom] = useState("");
  const [reach, setReach] = useState<Reach>("none");
  const many = targets.length > 1;
  const toggle = (role: string) => setRoles((all) => (all.includes(role) ? all.filter((r) => r !== role) : all.length < MAX_ROLES ? [...all, role] : all));
  const addCustom = () => {
    const role = custom.trim();
    if (role && !roles.some((r) => r.toLowerCase() === role.toLowerCase()) && roles.length < MAX_ROLES) setRoles([...roles, role]);
    setCustom("");
  };
  const refresh = () => {
    for (const key of ["lead", "companies", "linkedin", "linkedin-lead", "status", "runs"]) void queryClient.invalidateQueries({ queryKey: [key] });
    onDone();
  };
  const one = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/{company_id}/find-people", { params: { path: { company_id: targets[0]!.id } }, body: { roles, reach } })),
    onSuccess: refresh,
  });
  const bulk = useMutation({
    mutationFn: () => ok(client.POST("/api/companies/find-people", { body: { company_ids: targets.map((t) => t.id), roles, reach } })),
    onSuccess: refresh,
  });
  const run = many ? bulk : one;
  const done = run.isSuccess;
  const name = (id: string) => targets.find((t) => t.id === id)?.name ?? id;
  return (
    <Dialog
      title={many ? `Find more people at ${targets.length} leads` : `Find more people at ${targets[0]?.name ?? "this lead"}`}
      onClose={onClose}
      footer={
        done ? (
          <Button onClick={onClose}>Done</Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              Cancel
            </Button>
            <Button busy={run.isPending} onClick={() => run.mutate()}>
              {run.isPending ? "Searching…" : many ? `Search ${targets.length} leads` : "Search"}
            </Button>
          </>
        )
      }
    >
      {!done && (
        <div className="space-y-4">
          <Field label="Who to look for" hint={`Up to ${MAX_ROLES}. Leave empty to use the campaign's job titles.`}>
            <div className="flex flex-wrap gap-2" role="group" aria-label="Roles">
              {[...PRESETS, ...roles.filter((r) => !PRESETS.includes(r))].map((role) => {
                const on = roles.includes(role);
                return (
                  <button
                    key={role}
                    type="button"
                    aria-pressed={on}
                    onClick={() => toggle(role)}
                    className={cx("press h-8 rounded-full border px-3 text-small font-medium", on ? "border-primary bg-primary-soft text-primary" : "border-line-strong text-ink-2 hover:bg-surface-2")}
                  >
                    {role}
                  </button>
                );
              })}
            </div>
            <div className="mt-2 flex gap-2">
              <Input aria-label="Another role" placeholder="Another role, e.g. Head of Operations" value={custom} onChange={(e) => setCustom(e.target.value)} onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), addCustom())} />
              <Button variant="secondary" size="sm" onClick={addCustom} disabled={!custom.trim() || roles.length >= MAX_ROLES}>
                Add
              </Button>
            </div>
          </Field>
          <fieldset>
            <legend className="mb-1.5 text-small font-semibold text-ink">What to do with them</legend>
            <div className="space-y-2">
              {REACH.map(([value, label, hint]) => (
                <label key={value} className="flex cursor-pointer items-start gap-2 text-body">
                  <input type="radio" name="reach" className="mt-1 size-4 accent-[var(--primary)]" checked={reach === value} onChange={() => setReach(value)} />
                  <span>
                    <span className="font-medium">{label}</span>
                    <span className="block text-label text-muted">{hint}</span>
                  </span>
                </label>
              ))}
            </div>
          </fieldset>
          <Callout tone="info">Each lead uses a few AI credits (searches and one model call{reach === "linkedin" || reach === "both" ? ", and one more for each message" : ""}). Only people who work at the company are written to; the rest wait for you to confirm them.</Callout>
          <Problem error={run.error} />
        </div>
      )}
      {one.data && (
        <div className="space-y-3" role="status">
          <p className="text-body">
            Found {one.data.found}, added {one.data.added}
            {one.data.added ? `: ${one.data.works_here} work here, ${one.data.unsure} to confirm.` : "."}
            {one.data.retried ? " The lead goes on at the next run." : ""}
            {one.data.queued_run_id ? " A run is looking for their email addresses." : ""}
          </p>
          <People people={one.data.people ?? []} />
        </div>
      )}
      {bulk.data && (
        <div className="space-y-4" role="status">
          {bulk.data.queued_run_id && <p className="text-body">A run is looking for the email addresses asked for.</p>}
          {bulk.data.leads.map((lead) => (
            <div key={lead.company_id}>
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Link to="/leads/$companyId" params={{ companyId: lead.company_id }} className="font-semibold text-ink hover:text-primary">
                  {name(lead.company_id)}
                </Link>
                <span className="text-small text-muted">{lead.error ? "" : `found ${lead.found}, added ${lead.added}`}</span>
              </div>
              {lead.error ? <p className="text-small text-error">{lead.error}</p> : <People people={lead.people} />}
            </div>
          ))}
        </div>
      )}
    </Dialog>
  );
}
