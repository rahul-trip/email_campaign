import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Check, ClipboardCheck, Flame, Info, Pause, PlayCircle, TriangleAlert, UserPlus, X, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { go, inWorkspace, rememberWorkspace } from "../app/session";
import { cx } from "../lib/cx";
import { ago } from "../lib/format";

type Notice = Schemas["NotificationOut"];

const num = (value: unknown): number => (typeof value === "number" ? value : 0);
const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** What a notice says, an icon, and where clicking it goes (a path, or null to just mark it read). */
function describe(n: Notice): { text: string; to: string | null; icon: LucideIcon } {
  const slug = typeof n.data.slug === "string" ? n.data.slug : null;
  const workspace = typeof n.data.workspace_name === "string" ? n.data.workspace_name : "a workspace";
  const d = n.data;
  const at = (path: string) => (slug ? `${inWorkspace(slug)}${path}` : null);
  switch (n.kind) {
    case "join_requested": {
      const who = (typeof d.name === "string" && d.name) || (typeof d.email === "string" ? d.email : "Someone");
      return { text: `${who} asks to join ${workspace}`, to: at("settings?tab=team"), icon: UserPlus };
    }
    case "join_approved":
      return { text: `You can now open ${workspace}`, to: slug ? inWorkspace(slug) : "/", icon: Check };
    case "join_rejected":
      return { text: `${workspace} did not accept your request`, to: null, icon: X };
    case "drafts_ready": {
      const hot = num(d.hot);
      return { text: `${plural(num(d.drafts), "draft")} waiting for review${hot ? ` (${hot} hot)` : ""}`, to: at("review"), icon: ClipboardCheck };
    }
    case "hot_lead":
      return { text: `Hot lead: ${String(d.company ?? "a company")} (fit ${num(d.fit)})`, to: typeof d.company_id === "string" ? at(`leads/${d.company_id}`) : at("leads"), icon: Flame };
    case "needs_attention": {
      const parts = [num(d.held) ? `${num(d.held)} held` : "", num(d.failed) ? `${num(d.failed)} failed` : ""].filter(Boolean);
      return { text: `${plural(num(d.held) + num(d.failed), "lead")} need you: ${parts.join(", ")}`, to: at("attention"), icon: TriangleAlert };
    }
    case "auto_approved":
      return { text: `${plural(num(d.approved), "cold draft")} approved automatically and saved to your mailbox`, to: at("leads"), icon: Check };
    case "run_finished":
      return { text: `Your run finished: ${plural(num(d.moved), "lead")} moved, ${plural(num(d.drafts), "draft")} written`, to: typeof d.run_id === "string" ? at(`runs/${d.run_id}`) : at("runs"), icon: PlayCircle };
    case "run_failed":
      return { text: `A run failed${typeof d.reason === "string" && d.reason ? `: ${d.reason}` : ""}`, to: typeof d.run_id === "string" ? at(`runs/${d.run_id}`) : at("runs"), icon: TriangleAlert };
    case "discovery_paused":
      return { text: `Automatic discovery is paused: Review holds ${num(d.waiting)} drafts`, to: at("review"), icon: Pause };
    case "account":
      return { text: typeof d.text === "string" ? d.text : "A notice about your account", to: slug ? inWorkspace(slug) : null, icon: Info };
  }
}

/** The bell in the header: what happened that a person should see, newest first. */
export function NotificationBell() {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const notices = useQuery({ queryKey: ["notifications"], queryFn: () => ok(client.GET("/api/me/notifications")), refetchInterval: 30000 });
  const read = useMutation({
    mutationFn: (id: string | null) => ok(client.POST("/api/me/notifications/read", { body: { id } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["notifications"] }),
  });
  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  const unread = notices.data?.unread ?? 0;
  const open1 = (n: Notice) => {
    const { to } = describe(n);
    if (!n.read) read.mutate(n.id);
    setOpen(false);
    if (to) {
      if (typeof n.data.slug === "string" && n.kind === "join_approved") rememberWorkspace(n.data.slug);
      go(to);
    }
  };
  return (
    <div ref={root} className="relative" data-tour="notifications">
      <button type="button" aria-label={unread ? `Notifications, ${unread} unread` : "Notifications"} aria-expanded={open} onClick={() => setOpen(!open)} className="relative rounded-lg p-1.5 text-muted hover:bg-surface-low hover:text-ink">
        <Bell size={18} aria-hidden />
        {unread > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-error px-1 text-center font-mono text-[10px] font-semibold leading-4 text-white">{unread}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" className="absolute right-0 top-full z-50 mt-2 w-96 max-w-[calc(100vw-1.5rem)] rounded-lg border border-line bg-surface shadow-lg">
          <div className="flex items-center justify-between border-b border-line px-3 py-2 text-[12px]">
            <span className="font-semibold">Notifications</span>
            {unread > 0 && (
              <button type="button" onClick={() => read.mutate(null)} className="font-semibold text-primary hover:underline">
                Mark all read
              </button>
            )}
          </div>
          {(notices.data?.items ?? []).length === 0 ? (
            <p className="px-3 py-6 text-center text-[12px] text-muted">Nothing yet.</p>
          ) : (
            <ul className="max-h-96 divide-y divide-line overflow-y-auto">
              {notices.data!.items.map((n) => (
                <li key={n.id}>
                  <button type="button" onClick={() => open1(n)} className={cx("flex w-full items-start gap-2.5 px-3 py-2.5 text-left text-[13px] hover:bg-surface-low", !n.read && "bg-primary-fixed/40")}>
                    {(() => {
                      const Icon = describe(n).icon;
                      return <Icon className={cx("mt-0.5 size-4 shrink-0", n.kind === "hot_lead" ? "text-attention" : n.kind === "run_failed" ? "text-error" : "text-muted")} aria-hidden />;
                    })()}
                    <span className="min-w-0">
                      <span className={cx("block", !n.read && "font-semibold")}>{describe(n).text}</span>
                      <span className="mt-0.5 block text-[11px] text-muted">
                        {ago(n.created_at)}
                        {typeof n.data.workspace_name === "string" && n.kind !== "join_requested" && n.kind !== "join_approved" && n.kind !== "join_rejected" ? ` · ${n.data.workspace_name}` : ""}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
