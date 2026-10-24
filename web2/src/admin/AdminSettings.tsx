import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { Button, Callout, Card, Checkbox, Confirm, Field, PageHeader, Problem, QueryState, SaveNote, Textarea } from "../components/ui";

export function AdminSettingsPage() {
  const settings = useQuery({ queryKey: ["admin", "settings"], queryFn: () => ok(client.GET("/api/admin/settings")) });
  return (
    <>
      <PageHeader title="Platform settings" subtitle="Switches that affect every customer." />
      <QueryState query={settings}>{(s) => <Form key={s.version} s={s} />}</QueryState>
    </>
  );
}

type Settings = Schemas["PlatformSettingsOut"];

function Form({ s }: { s: Settings }) {
  const queryClient = useQueryClient();
  const [announcement, setAnnouncement] = useState(s.announcement);
  const [stop, setStop] = useState<"runs" | null>(null);
  useEffect(() => setAnnouncement(s.announcement), [s.announcement]);
  const patch = useMutation({
    mutationFn: (changes: Partial<Omit<Settings, "version">>) => ok(client.PATCH("/api/admin/settings", { body: { version: s.version, ...changes } })),
    onSuccess: () => {
      setStop(null);
      void queryClient.invalidateQueries({ queryKey: ["admin"] });
    },
  });
  return (
    <div className="space-y-4">
      <Card tour="admin-kill" title="Stop everything" subtitle="The kill switches. Customers can still sign in and read.">
        {s.kill_runs && (
          <Callout tone="error" className="mb-3" title="The engine is stopped for every customer">
            No research, no emails, no drafts anywhere until you switch it back on.
          </Callout>
        )}
        <div className="flex flex-wrap items-center gap-3">
          {s.kill_runs ? (
            <Button busy={patch.isPending} onClick={() => patch.mutate({ kill_runs: false })}>
              Switch the engine back on
            </Button>
          ) : (
            <Button variant="danger" onClick={() => setStop("runs")}>
              Stop the engine for everyone…
            </Button>
          )}
        </div>
        <Problem error={patch.error} className="mt-3" />
      </Card>
      <Card title="Announcement" subtitle="Shown at the top of every workspace. Empty: none.">
        <Field label="Message">
          <Textarea rows={2} value={announcement} onChange={(e) => setAnnouncement(e.target.value)} className="w-full" />
        </Field>
        <div className="mt-3 flex items-center gap-3">
          <Button busy={patch.isPending} disabled={announcement === s.announcement} onClick={() => patch.mutate({ announcement })}>
            Save
          </Button>
          <SaveNote mutation={patch} done="Saved." />
        </div>
      </Card>
      <Card title="Superadmin (alpha only)" subtitle="Lets a superadmin open any workspace, read-only, for support. Every visit is audited. Switch it off once a proper support role exists.">
        <Checkbox label="A superadmin may view any workspace" checked={s.superadmin_enabled} onChange={(on) => patch.mutate({ superadmin_enabled: on })} />
      </Card>
      {stop === "runs" && (
        <Confirm title="Stop the engine for everyone?" confirmLabel="Stop everything" typed="STOP" busy={patch.isPending} error={patch.error} onClose={() => setStop(null)} onConfirm={() => patch.mutate({ kill_runs: true })}>
          Every customer's research, email finding, writing and drafting stops at once. Leads are kept and continue when you switch it back on.
        </Confirm>
      )}
    </div>
  );
}
