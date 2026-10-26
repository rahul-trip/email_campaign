import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { client, ok } from "../api/client";
import { Button, Card, Empty, Field, Input, PageHeader, Problem, QueryState, Table, Td, Th } from "../components/ui";
import { DirectoryBrowser } from "./DirectoryBrowser";
import { When } from "./bits";

const usd = (micro: number) => `$${(micro / 1e6).toFixed(2)}`;

export function DirectoryPage() {
  const queryClient = useQueryClient();
  const overview = useQuery({ queryKey: ["admin", "directory"], queryFn: () => ok(client.GET("/api/admin/directory")) });
  const resolve = useMutation({
    mutationFn: (v: { id: string; accept: boolean }) => ok(client.POST("/api/admin/directory/flags/{flag_id}/resolve", { params: { path: { flag_id: v.id } }, body: { accept: v.accept, note: "" } })),
    onSuccess: (data) => queryClient.setQueryData(["admin", "directory"], data),
  });
  const [key, setKey] = useState("");
  const history = useQuery({
    queryKey: ["admin", "directory", "history", key],
    queryFn: () => ok(client.GET("/api/admin/directory/history", { params: { query: { key } } })),
    enabled: key.trim().length >= 3,
  });
  return (
    <>
      <PageHeader title="Lead directory" subtitle="Verified facts shared between customers. Nothing here shows who contributed or looked something up." />
      <QueryState query={overview} rows={4}>
        {(data) => {
          const f = data.figures;
          return (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-5" data-tour="admin-directory">
                <Tile label="Companies" value={f.companies} />
                <Tile label="People" value={f.people} />
                <Tile label="Addresses" value={f.emails} />
                <Tile label="Hits this month" value={`${f.hits} of ${f.lookups}`} />
                <Tile label="Saved this month" value={usd(f.saved_micro_usd)} />
              </div>
              <Card title={`Reports to decide (${data.flags.length})`} subtitle="Until you decide, the reported address is not served to anyone.">
                <Problem error={resolve.error} className="mb-2" />
                {data.flags.length === 0 ? (
                  <Empty title="Nothing waiting" />
                ) : (
                  <Table>
                    <thead>
                      <tr>
                        <Th>Fact</Th>
                        <Th>What is wrong</Th>
                        <Th>Reported</Th>
                        <Th />
                      </tr>
                    </thead>
                    <tbody>
                      {data.flags.map((flag) => (
                        <tr key={flag.id}>
                          <Td className="font-mono text-xs">{flag.target_key}</Td>
                          <Td>{flag.field.replaceAll("_", " ")}</Td>
                          <Td className="text-muted">
                            <When iso={flag.created_at} time />
                          </Td>
                          <Td className="space-x-1 text-right whitespace-nowrap">
                            <Button size="sm" variant="secondary" onClick={() => resolve.mutate({ id: flag.id, accept: true })}>
                              Accept correction
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => resolve.mutate({ id: flag.id, accept: false })}>
                              Reject
                            </Button>
                          </Td>
                        </tr>
                      ))}
                    </tbody>
                  </Table>
                )}
              </Card>
              <DirectoryBrowser />
              <Card title="Look up one fact" subtitle="An address or a domain: when each source last confirmed it.">
                <Field label="Address or domain">
                  <Input value={key} onChange={(e) => setKey(e.target.value)} className="w-72" />
                </Field>
                {history.data && (
                  <ul className="mt-3 space-y-1 text-xs">
                    {history.data.length === 0 && <li className="text-muted">Nothing observed.</li>}
                    {history.data.map((row, i) => (
                      <li key={i}>
                        <When iso={row.at} time /> · {row.target} · from {row.source}
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
              {f.unfolded > 0 && <p className="text-xs text-muted">{f.unfolded} new observations are waiting for the next pass.</p>}
            </div>
          );
        }}
      </QueryState>
    </>
  );
}

function Tile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-3">
      <div className="text-[11px] text-muted">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}
