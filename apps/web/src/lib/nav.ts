import {
  BookOpen,
  Calendar,
  CalendarDays,
  ClipboardList,
  FileText,
  FlaskConical,
  HelpCircle,
  LibraryBig,
  LayoutDashboard,
  ListChecks,
  MessageSquare,
  Settings,
  ShieldCheck,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { MessageKey } from "@/i18n/translate";

export type NavItem = {
  href: string;
  /** Message keys, so labels follow the interface language. */
  label: MessageKey;
  description: MessageKey;
  icon: LucideIcon;
  /** The roadmap step in which this page becomes functional. */
  step: number;
  /** True once the page is a real screen rather than a placeholder. */
  built: boolean;
  /** Shown only to administrators. */
  adminOnly?: boolean;
  /** Which block of the sidebar it belongs to. */
  group: NavGroup;
};

/** The five hubs. Settings, Help and Admin live in the profile menu ("account"). */
export type NavGroup = "home" | "study" | "plan" | "community" | "lab" | "account";

export type Hub = { id: Exclude<NavGroup, "account">; label: MessageKey; icon: LucideIcon };

export const HUBS: Hub[] = [
  { id: "home", label: "nav.hub.home", icon: LayoutDashboard },
  { id: "study", label: "nav.hub.study", icon: BookOpen },
  { id: "plan", label: "nav.hub.plan", icon: CalendarDays },
  { id: "community", label: "nav.hub.community", icon: Users },
  { id: "lab", label: "nav.hub.lab", icon: FlaskConical },
];

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "nav.dashboard", description: "navdesc.dashboard", icon: LayoutDashboard, step: 1, built: true, group: "home" },
  { href: "/subjects", label: "nav.subjects", description: "navdesc.subjects", icon: BookOpen, step: 1, built: true, group: "study" },
  { href: "/chat", label: "nav.chat", description: "navdesc.chat", icon: MessageSquare, step: 2, built: true, group: "study" },
  { href: "/quizzes", label: "nav.quizzes", description: "navdesc.quizzes", icon: ListChecks, step: 3, built: true, group: "study" },
  { href: "/planner", label: "nav.planner", description: "navdesc.planner", icon: ClipboardList, step: 4, built: true, group: "plan" },
  { href: "/calendar", label: "nav.calendar", description: "navdesc.calendar", icon: Calendar, step: 4, built: true, group: "plan" },
  { href: "/assignments", label: "nav.assignments", description: "navdesc.assignments", icon: FileText, step: 4, built: true, group: "plan" },
  { href: "/materials", label: "nav.materials", description: "navdesc.materials", icon: LibraryBig, step: 5, built: true, group: "community" },
  { href: "/library", label: "nav.library", description: "navdesc.library", icon: Users, step: 5, built: true, group: "community" },
  { href: "/eval", label: "nav.eval", description: "navdesc.eval", icon: FlaskConical, step: 2, built: true, group: "lab" },
  { href: "/guide", label: "nav.guide", description: "navdesc.guide", icon: HelpCircle, step: 5, built: true, group: "account" },
  { href: "/settings", label: "nav.settings", description: "navdesc.settings", icon: Settings, step: 4, built: true, group: "account" },
  { href: "/admin", label: "nav.admin", description: "navdesc.admin", icon: ShieldCheck, step: 5, built: true, adminOnly: true, group: "account" },
];

/** The hub a page belongs to, and its sibling pages (for the tab strip under the top bar). */
export function hubOf(pathname: string): { hub: Hub; items: NavItem[] } | null {
  const current = NAV_ITEMS.find((item) => pathname === item.href || pathname.startsWith(`${item.href}/`));
  if (!current || current.group === "account") return null;
  const hub = HUBS.find((candidate) => candidate.id === current.group);
  return hub ? { hub, items: NAV_ITEMS.filter((item) => item.group === current.group) } : null;
}
