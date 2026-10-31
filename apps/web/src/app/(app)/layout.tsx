import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { AskAiPanel } from "@/components/shell/ask-ai";
import { PageFrame } from "@/components/shell/page-frame";
import { COURSE_COOKIE } from "@/components/shell/course";
import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";
import { VerifyBanner } from "@/components/verify-banner";
import { fetchMe, serverFetch } from "@/lib/api-server";
import type { Subject, SubjectPage } from "@/lib/types";

export default async function AppLayout({ children }: { children: ReactNode }) {
  const user = await fetchMe();
  if (!user) redirect("/login");
  if (!user.onboarding_completed) redirect("/onboarding");

  // The course switcher needs the student's subjects on every page. A failure here must not take
  // the page down, so it falls back to an empty list.
  let subjects: Subject[] = [];
  try {
    const response = await serverFetch("/subjects?limit=100");
    if (response.ok) subjects = ((await response.json()) as SubjectPage).items;
  } catch {
    subjects = [];
  }
  const saved = (await cookies()).get(COURSE_COOKIE)?.value ?? null;
  const currentCourse = subjects.some((subject) => subject.id === saved) ? saved : null;

  return (
    <div className="flex h-dvh">
      <Sidebar user={user} subjects={subjects} currentCourse={currentCourse} />
      <div className="flex min-w-0 flex-1 flex-col">
        {user.email_verified ? null : <VerifyBanner email={user.email} />}
        <Topbar user={user} subjects={subjects} currentCourse={currentCourse} />
        <PageFrame>{children}</PageFrame>
      </div>
      <AskAiPanel subjects={subjects} courseId={currentCourse} />
    </div>
  );
}
