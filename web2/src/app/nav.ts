import type { LucideIcon } from "lucide-react";
import {
  BarChart3, ClipboardCheck, LayoutDashboard, Megaphone, PlayCircle, Reply, Send, Settings, ShieldCheck,
  TriangleAlert, UserPlus, Users,
} from "lucide-react";

/**
 * A sidebar entry. ``soon`` items belong to a later phase: shown so the layout does not change
 * when they arrive, but not clickable. ``soonNote`` says which phase brings them.
 */
export type NavItem = { to: string; label: string; icon: LucideIcon; badge?: "review" | "attention"; soon?: boolean; soonNote?: string };
export type NavGroup = { label: string; items: NavItem[] };

// Driven by data so a module can be added, hidden until its phase ships, or hidden per role later.
export const NAV: NavGroup[] = [
  { label: "Home", items: [{ to: "/", label: "Dashboard", icon: LayoutDashboard }] },
  {
    label: "Work",
    items: [
      { to: "/review", label: "Review", icon: ClipboardCheck, badge: "review" },
      { to: "/attention", label: "Needs attention", icon: TriangleAlert, badge: "attention" },
      { to: "/replies", label: "Replies", icon: Reply, soon: true, soonNote: "Reading replies arrives in Phase 4." },
    ],
  },
  {
    label: "Pipeline",
    items: [
      { to: "/leads", label: "Leads", icon: Users },
      { to: "/targets", label: "Add leads", icon: UserPlus },
      { to: "/runs", label: "Runs", icon: PlayCircle },
    ],
  },
  {
    label: "Outreach",
    items: [
      { to: "/campaigns", label: "Campaigns", icon: Megaphone },
      { to: "/sending", label: "Sending", icon: Send, soon: true, soonNote: "Automatic sending arrives in Phase 5." },
    ],
  },
  { label: "Insights", items: [{ to: "/reports", label: "Reports", icon: BarChart3 }] },
  { label: "Compliance", items: [{ to: "/compliance", label: "Policies and privacy", icon: ShieldCheck }] },
  { label: "Settings", items: [{ to: "/settings", label: "Settings", icon: Settings }] },
];
