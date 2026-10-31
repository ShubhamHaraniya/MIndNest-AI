import { cookies } from "next/headers";
import { notFound } from "next/navigation";

import { COURSE_COOKIE } from "@/components/shell/course";
import { CourseWorkspace } from "@/components/subjects/workspace";
import { serverFetch } from "@/lib/api-server";
import type { Subject } from "@/lib/types";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = UUID.test(id) ? await serverFetch(`/subjects/${id}`) : null;
  const name = response?.ok ? ((await response.json()) as Subject).name : null;
  return { title: `${name ?? "Course"} · MindNest AI` };
}

export default async function SubjectDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await serverFetch(`/subjects/${encodeURIComponent(id)}`);
  // A malformed id (422) and someone else's subject (404) both read as "not found" to a visitor.
  if (response.status === 404 || response.status === 422) notFound();
  if (!response.ok) throw new Error(`Could not load the subject (HTTP ${response.status}).`);
  const subject = (await response.json()) as Subject;
  const chosen = (await cookies()).get(COURSE_COOKIE)?.value ?? null;

  return <CourseWorkspace initial={subject} currentId={chosen} />;
}
