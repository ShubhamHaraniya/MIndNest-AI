import { cookies } from "next/headers";

import { AssignmentsHub } from "@/components/assignments-hub";
import { COURSE_COOKIE } from "@/components/shell/course";
import { serverFetch } from "@/lib/api-server";
import type { SubjectPage } from "@/lib/types";

export const metadata = { title: "Assignments · MindNest AI" };

export default async function AssignmentsPage() {
  const response = await serverFetch("/subjects?limit=100");
  const subjects = response.ok ? ((await response.json()) as SubjectPage).items : [];
  // The sidebar's course, but only if it is really one of this student's courses.
  const chosen = (await cookies()).get(COURSE_COOKIE)?.value ?? null;
  const courseId = chosen && subjects.some((subject) => subject.id === chosen) ? chosen : null;
  return <AssignmentsHub subjects={subjects} courseId={courseId} />;
}
