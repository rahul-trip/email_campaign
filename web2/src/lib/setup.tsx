import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { client, ok, type Schemas } from "../api/client";
import { Button } from "../components/ui";

export type SetupItem = Schemas["SetupItemOut"];

/** What the workspace still has to set up, from the server (the same list everywhere). */
export const useSetup = () => useQuery({ queryKey: ["setup"], queryFn: () => ok(client.GET("/api/setup")) });

/** Open the page an item says to fix it on. */
export function useOpen() {
  const navigate = useNavigate();
  return (where: string) => {
    if (where.startsWith("settings:")) void navigate({ to: "/settings", search: { tab: where.slice(9) as "profile" | "mailboxes" } });
    else void navigate({ to: where === "campaigns" ? "/campaigns" : where === "compliance" ? "/compliance" : "/targets" });
  };
}

const LABEL: Record<string, string> = { "settings:profile": "Fill in", "settings:mailboxes": "Open mailboxes", campaigns: "Open campaigns", compliance: "Open policies", targets: "Add leads" };

/** The checklist: a tick, a warning or a missing mark per item, and a button to fix it. */
export function SetupList({ items, onOpen }: { items: SetupItem[]; onOpen: (where: string) => void }) {
  return (
    <ul className="divide-y divide-line">
      {items.map((item) => (
        <li key={item.key} className="flex items-start gap-3 py-3">
          {item.status === "ok" ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-good" aria-label="Done" />
          ) : (
            <AlertTriangle className={`mt-0.5 size-4 shrink-0 ${item.status === "missing" ? "text-error" : "text-attention"}`} aria-label={item.status === "missing" ? "Missing" : "Worth a look"} />
          )}
          <div className="min-w-0 flex-1">
            <div className="text-[13px] font-medium">{item.title}</div>
            <div className="text-xs text-muted">{item.detail}</div>
          </div>
          {item.status !== "ok" && (
            <Button size="sm" variant="secondary" onClick={() => onOpen(item.where)}>
              {LABEL[item.where] ?? "Open"}
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
