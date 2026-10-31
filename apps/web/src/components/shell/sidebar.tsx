import { Brand } from "@/components/brand";
import { CourseSwitcher } from "@/components/shell/course-switcher";
import { SidebarNav } from "@/components/shell/sidebar-nav";
import type { Subject, User } from "@/lib/types";

/** The sidebar floats: a rounded glass slab inset from the window edge, so the aurora shows around
 *  it. Brand and course on top, the five hubs scrolling in the middle. */
export function Sidebar({ user, subjects, currentCourse }: { user: User; subjects: Subject[]; currentCourse: string | null }) {
  return (
    <aside className="relative z-30 hidden h-dvh w-[17.5rem] shrink-0 p-3 pr-0 lg:block">
      <div className="glass flex h-full flex-col rounded-3xl">
        <Brand href="/dashboard" className="h-16 shrink-0 px-5" />
        <div className="px-3 pb-3">
          <CourseSwitcher subjects={subjects} currentId={currentCourse} />
        </div>
        <div className="mx-4 h-px bg-gradient-to-r from-transparent via-border-strong to-transparent" aria-hidden />
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-6 pt-4">
          <SidebarNav isAdmin={user.is_admin} />
        </div>
      </div>
    </aside>
  );
}
