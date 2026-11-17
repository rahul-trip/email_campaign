import type { LucideIcon } from "lucide-react";
import {
  BarChart3, ClipboardCheck, LayoutDashboard, Megaphone, MessageSquareText, PlayCircle, Settings, ShieldCheck,
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
  {
    label: "Work",
    items: [
      { to: "/", label: "Dashboard", icon: LayoutDashboard },
      { to: "/review", label: "Review", icon: ClipboardCheck, badge: "review" },
      { to: "/attention", label: "Needs attention", icon: TriangleAlert, badge: "attention" },
    ],
  },
  {
    label: "Leads",
    items: [
      { to: "/leads", label: "Leads", icon: Users },
      { to: "/linkedin", label: "LinkedIn", icon: MessageSquareText },
      { to: "/targets", label: "Add leads", icon: UserPlus },
      { to: "/runs", label: "Runs", icon: PlayCircle },
      { to: "/campaigns", label: "Campaigns", icon: Megaphone },
    ],
  },
  {
    label: "Workspace",
    items: [
      { to: "/reports", label: "Reports", icon: BarChart3 },
      { to: "/compliance", label: "Policies and privacy", icon: ShieldCheck },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
  // Replies (Phase 4) and Sending (Phase 5) return here, with `soon: true`, until they ship.
];
