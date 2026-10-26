/** Staff browse the directory and add, change or remove what it holds. Every change is audited. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Card, Checkbox, Confirm, Dialog, Empty, Field, Input, Problem, QueryState, Select, Table, Tabs, Td, Th } from "../components/ui";
import { Pill, When } from "./bits";

type Entry = Schemas["DirectoryEntryOut"];
type Company = Schemas["DirectoryCompanyOut"];
const SIZE = 25;

export function DirectoryBrowser() {
  const [tab, setTab] = useState<"people" | "companies">("people");
  return (
    <Card tour="admin-directory-browse" title="Browse and edit" subtitle="Everything the directory holds. A change here is served to every customer at once.">
      <Tabs
        label="Directory"
        tabs={[
          ["people", "People and addresses"],
          ["companies", "Companies and patterns"],
        ]}
        value={tab}
        onChange={setTab}
      >
        {tab === "people" ? <People /> : <Companies />}
      </Tabs>
    </Card>
  );
}

function Pager({ page, total, onPage }: { page: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / SIZE));
  return (
    <div className="mt-3 flex items-center justify-between text-xs text-muted">
      <span>
        {total} in all · page {page + 1} of {pages}
      </span>
      <span className="space-x-1">
        <Button size="sm" variant="secondary" disabled={page === 0} onClick={() => onPage(page - 1)}>
          Previous
        </Button>
        <Button size="sm" variant="secondary" disabled={page + 1 >= pages} onClick={() => onPage(page + 1)}>
          Next
        </Button>
      </span>
    </div>
  );
}

// ------------------------------------------------------------------ people and addresses

function People() {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<Entry | "new" | null>(null);
  const [removing, setRemoving] = useState<Entry | null>(null);
  const [block, setBlock] = useState(false);
  const list = useQuery({
    queryKey: ["admin", "directory", "entries", q, page],
    queryFn: () => ok(client.GET("/api/admin/directory/entries", { params: { query: { q, page } } })),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["admin", "directory"] });
  const remove = useMutation({
    mutationFn: async (e: Entry) => {
      const r = await client.DELETE("/api/admin/directory/entries/{entry_id}", { params: { path: { entry_id: e.id }, query: { block } } });
      if (!r.response.ok) throw new Error("That could not be removed.");
    },
    onSuccess: () => {
      setRemoving(null);
      setBlock(false);
      refresh();
    },
  });
  return (
    <>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div className="w-72">
          <Input aria-label="Search the directory" placeholder="Search address, name or company" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} className="w-full" />
        </div>
        <Button onClick={() => setEditing("new")}>Add a person</Button>
      </div>
      <QueryState query={list} rows={4}>
        {(data) =>
          data.entries.length === 0 ? (
            <Empty title={q ? "Nothing matches" : "The directory is empty"} />
          ) : (
            <>
              <div className="overflow-x-auto rounded-lg border border-line">
                <Table>
                  <thead>
                    <tr>
                      <Th>Person</Th>
                      <Th>Address</Th>
                      <Th>Company</Th>
                      <Th>Status</Th>
                      <Th>Verified</Th>
                      <Th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.entries.map((e) => (
                      <tr key={e.id}>
                        <Td>
                          <span className="font-medium">{e.full_name}</span>
                          <span className="block text-[11px] text-muted">{e.title ?? "no title"}</span>
                        </Td>
                        <Td className="font-mono text-xs">{e.email}</Td>
                        <Td>{e.company_domain}</Td>
                        <Td>
                          {e.status === "verified" ? <Pill tone="good">verified</Pill> : <Pill tone={e.status === "invalid" ? "error" : "attention"}>{e.status}</Pill>}
                          {e.employment_status === "left" && <span className="ml-1 text-[11px] text-muted">left the company</span>}
                        </Td>
                        <Td className="whitespace-nowrap text-xs text-muted">
                          <When iso={e.verified_at} /> · {e.source}
                        </Td>
                        <Td className="space-x-1 whitespace-nowrap text-right">
                          <Button size="sm" variant="ghost" onClick={() => setEditing(e)}>
                            Edit
                          </Button>
                          <Button size="sm" variant="danger-ghost" onClick={() => setRemoving(e)}>
                            Remove
                          </Button>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
              <Pager page={page} total={data.total} onPage={setPage} />
            </>
          )
        }
      </QueryState>
      {editing && <EditEntry entry={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); refresh(); }} />}
      {removing && (
        <Confirm title={`Remove ${removing.email}?`} confirmLabel="Remove" busy={remove.isPending} error={remove.error} onClose={() => { setRemoving(null); setBlock(false); }} onConfirm={() => remove.mutate(removing)}>
          It stops being served to every customer, with anything noted about it.
          <div className="mt-3">
            <Checkbox label="Also never add this address again" hint="Use it when the person asked to be removed." checked={block} onChange={setBlock} />
          </div>
        </Confirm>
      )}
    </>
  );
}

function EditEntry({ entry, onClose, onDone }: { entry: Entry | null; onClose: () => void; onDone: () => void }) {
  const [email, setEmail] = useState(entry?.email ?? "");
  const [first, setFirst] = useState(entry?.first_name ?? "");
  const [last, setLast] = useState(entry?.last_name ?? "");
  const [domain, setDomain] = useState(entry?.company_domain ?? "");
  const [title, setTitle] = useState(entry?.title ?? "");
  const [linkedin, setLinkedin] = useState(entry?.linkedin_url ?? "");
  const [status, setStatus] = useState(entry?.status ?? "verified");
  const [employment, setEmployment] = useState(entry?.employment_status ?? "unknown");
  const save = useMutation({
    mutationFn: () =>
      entry
        ? ok(
            client.PATCH("/api/admin/directory/entries/{entry_id}", {
              params: { path: { entry_id: entry.id } },
              body: { email, first_name: first, last_name: last, title, linkedin_url: linkedin, status: status as "verified", employment_status: employment as "current" },
            }),
          )
        : ok(client.POST("/api/admin/directory/entries", { body: { email, first_name: first, last_name: last, company_domain: domain, title: title || null, linkedin_url: linkedin || null } })),
    onSuccess: onDone,
  });
  return (
    <Dialog
      title={entry ? `Edit ${entry.full_name}` : "Add a person"}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={save.isPending} disabled={!email.includes("@") || !first.trim() || !last.trim() || (!entry && !domain.includes("."))} onClick={() => save.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <Field label="First name">
          <Input value={first} onChange={(e) => setFirst(e.target.value)} className="w-full" />
        </Field>
        <Field label="Last name">
          <Input value={last} onChange={(e) => setLast(e.target.value)} className="w-full" />
        </Field>
      </div>
      <Field label="Work email">
        <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full" />
      </Field>
      {!entry && (
        <Field label="Company website" hint="For example acme.com.">
          <Input value={domain} onChange={(e) => setDomain(e.target.value)} className="w-full" />
        </Field>
      )}
      <Field label="Job title">
        <Input value={title} onChange={(e) => setTitle(e.target.value)} className="w-full" />
      </Field>
      <Field label="LinkedIn profile">
        <Input value={linkedin} onChange={(e) => setLinkedin(e.target.value)} className="w-full" />
      </Field>
      {entry && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Address status" hint="Only verified is served.">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="verified">Verified</option>
              <option value="disputed">Disputed</option>
              <option value="invalid">Invalid</option>
            </Select>
          </Field>
          <Field label="Still at the company?">
            <Select value={employment} onChange={(e) => setEmployment(e.target.value)}>
              <option value="unknown">Unknown</option>
              <option value="current">Yes</option>
              <option value="left">Left</option>
            </Select>
          </Field>
        </div>
      )}
      <Problem error={save.error} />
    </Dialog>
  );
}

// ------------------------------------------------------------------ companies and patterns

function Companies() {
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<Company | "new" | null>(null);
  const [removing, setRemoving] = useState<Company | null>(null);
  const list = useQuery({
    queryKey: ["admin", "directory", "companies", q, page],
    queryFn: () => ok(client.GET("/api/admin/directory/companies", { params: { query: { q, page } } })),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["admin", "directory"] });
  const remove = useMutation({
    mutationFn: async (c: Company) => {
      const r = await client.DELETE("/api/admin/directory/companies/{domain}", { params: { path: { domain: c.domain } } });
      if (!r.response.ok) throw new Error("That could not be removed.");
    },
    onSuccess: () => {
      setRemoving(null);
      refresh();
    },
  });
  return (
    <>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div className="w-72">
          <Input aria-label="Search companies" placeholder="Search by domain" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} className="w-full" />
        </div>
        <Button onClick={() => setEditing("new")}>Add a company</Button>
      </div>
      <QueryState query={list} rows={3}>
        {(data) =>
          data.companies.length === 0 ? (
            <Empty title={q ? "Nothing matches" : "No company patterns yet"} />
          ) : (
            <>
              <div className="overflow-x-auto rounded-lg border border-line">
                <Table>
                  <thead>
                    <tr>
                      <Th>Company</Th>
                      <Th>Country</Th>
                      <Th>Email pattern</Th>
                      <Th>Agreeing</Th>
                      <Th />
                    </tr>
                  </thead>
                  <tbody>
                    {data.companies.map((c) => (
                      <tr key={c.id}>
                        <Td>
                          <span className="font-medium">{c.domain}</span>
                          {c.name && <span className="block text-[11px] text-muted">{c.name}</span>}
                        </Td>
                        <Td>{c.country_code ?? "—"}</Td>
                        <Td className="font-mono text-xs">{c.email_pattern ?? "—"}</Td>
                        <Td>{c.pattern_confidence}</Td>
                        <Td className="space-x-1 whitespace-nowrap text-right">
                          <Button size="sm" variant="ghost" onClick={() => setEditing(c)}>
                            Edit
                          </Button>
                          <Button size="sm" variant="danger-ghost" onClick={() => setRemoving(c)}>
                            Remove
                          </Button>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </Table>
              </div>
              <Pager page={page} total={data.total} onPage={setPage} />
            </>
          )
        }
      </QueryState>
      {editing && <EditCompany company={editing === "new" ? null : editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); refresh(); }} />}
      {removing && (
        <Confirm title={`Remove ${removing.domain}?`} confirmLabel="Remove" busy={remove.isPending} error={remove.error} onClose={() => setRemoving(null)} onConfirm={() => remove.mutate(removing)}>
          Its stored pattern stops being used. People and addresses at it are not removed.
        </Confirm>
      )}
    </>
  );
}

function EditCompany({ company, onClose, onDone }: { company: Company | null; onClose: () => void; onDone: () => void }) {
  const [domain, setDomain] = useState(company?.domain ?? "");
  const [name, setName] = useState(company?.name ?? "");
  const [country, setCountry] = useState(company?.country_code ?? "");
  const [pattern, setPattern] = useState(company?.email_pattern ?? "");
  const save = useMutation({
    mutationFn: () => ok(client.PUT("/api/admin/directory/companies/{domain}", { params: { path: { domain: domain.trim() } }, body: { name: name || null, country_code: country || null, email_pattern: pattern || null } })),
    onSuccess: onDone,
  });
  return (
    <Dialog
      title={company ? `Edit ${company.domain}` : "Add a company"}
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button busy={save.isPending} disabled={!domain.includes(".")} onClick={() => save.mutate()}>
            Save
          </Button>
        </>
      }
    >
      <Field label="Website">
        <Input value={domain} disabled={Boolean(company)} onChange={(e) => setDomain(e.target.value)} className="w-full" />
      </Field>
      <Field label="Name">
        <Input value={name} onChange={(e) => setName(e.target.value)} className="w-full" />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Country code" hint="Two letters, for example GB.">
          <Input value={country} maxLength={2} onChange={(e) => setCountry(e.target.value)} className="w-24" />
        </Field>
        <Field label="Email pattern" hint="For example {first}.{last}. A pattern set here is trusted.">
          <Input value={pattern} onChange={(e) => setPattern(e.target.value)} className="w-full" />
        </Field>
      </div>
      <Problem error={save.error} />
    </Dialog>
  );
}
