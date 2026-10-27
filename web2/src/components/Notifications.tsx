import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { client, ok, type Schemas } from "../api/client";
import { go, inWorkspace, rememberWorkspace } from "../app/session";
import { cx } from "../lib/cx";
import { ago } from "../lib/format";

type Notice = Schemas["NotificationOut"];

/** What a notice says, and where clicking it goes (a path, or null to just mark it read). */
function describe(n: Notice): { text: string; to: string | null } {
  const slug = typeof n.data.slug === "string" ? n.data.slug : null;
  const workspace = typeof n.data.workspace_name === "string" ? n.data.workspace_name : "a workspace";
  if (n.kind === "join_requested") {
    const who = (typeof n.data.name === "string" && n.data.name) || (typeof n.data.email === "string" ? n.data.email : "Someone");
    return { text: `${who} asks to join ${workspace}`, to: slug ? `${inWorkspace(slug)}settings?tab=team` : null };
  }
  if (n.kind === "join_approved") return { text: `You can now open ${workspace}`, to: slug ? inWorkspace(slug) : "/" };
  return { text: `${workspace} did not accept your request`, to: null };
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
        <div role="dialog" aria-label="Notifications" className="absolute right-0 top-full z-50 mt-2 w-80 rounded-lg border border-line bg-surface shadow-lg">
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
                  <button type="button" onClick={() => open1(n)} className={cx("block w-full px-3 py-2.5 text-left text-[13px] hover:bg-surface-low", !n.read && "bg-primary-fixed/40")}>
                    <span className={cx(!n.read && "font-semibold")}>{describe(n).text}</span>
                    <span className="mt-0.5 block text-[11px] text-muted">{ago(n.created_at)}</span>
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
