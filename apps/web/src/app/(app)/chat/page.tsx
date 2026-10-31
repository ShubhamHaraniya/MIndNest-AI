import { cookies } from "next/headers";

import { ChatWorkspace } from "@/components/chat/workspace";
import { COURSE_COOKIE } from "@/components/shell/course";
import { serverFetch } from "@/lib/api-server";
import type { SubjectPage } from "@/lib/types";

export const metadata = { title: "Chat · MindNest AI" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function ChatPage({ searchParams }: { searchParams: Promise<{ c?: string }> }) {
  const { c } = await searchParams;
  const response = await serverFetch("/subjects?limit=100");
  const subjects = response.ok ? ((await response.json()) as SubjectPage).items : [];
  // The sidebar's course, but only if it is really one of this student's courses.
  const chosen = (await cookies()).get(COURSE_COOKIE)?.value ?? null;
  const courseId = chosen && subjects.some((s) => s.id === chosen) ? chosen : null;

  return (
    <ChatWorkspace
      subjects={subjects}
      initialConversationId={c && UUID.test(c) ? c : null}
      courseId={courseId}
    />
  );
}
