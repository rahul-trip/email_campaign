import type { LucideIcon } from "lucide-react";
import { BarChart3, ClipboardCheck, LayoutDashboard, Megaphone, MessageSquareText, Radar, Settings, ShieldCheck, TriangleAlert, UserPlus, Users } from "lucide-react";

/** A sidebar entry. Paths are the same as web2's, so every old link and bookmark still opens. */
export type NavItem = { to: string; label: string; icon: LucideIcon; badge?: "review" | "attention" | "linkedin"; tour?: string };
export type NavGroup = { label: string; items: NavItem[] };

export const NAV: NavGroup[] = [
  {
    label: "Work",
    items: [
      { to: "/", label: "Today", icon: LayoutDashboard },
      { to: "/review", label: "Review", icon: ClipboardCheck, badge: "review" },
      { to: "/attention", label: "Needs attention", icon: TriangleAlert, badge: "attention" },
      { to: "/linkedin", label: "LinkedIn", icon: MessageSquareText, badge: "linkedin" },
    ],
  },
  {
    label: "Leads",
    items: [
      { to: "/leads", label: "Leads", icon: Users },
      { to: "/targets", label: "Add leads", icon: UserPlus },
      { to: "/runs", label: "Discovery runs", icon: Radar },
      { to: "/campaigns", label: "Campaigns", icon: Megaphone },
    ],
  },
  {
    label: "Workspace",
    items: [
      { to: "/reports", label: "Reports", icon: BarChart3 },
      { to: "/compliance", label: "Policies & privacy", icon: ShieldCheck },
      { to: "/settings", label: "Settings", icon: Settings },
    ],
  },
];
