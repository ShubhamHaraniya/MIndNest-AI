import { AssignmentWorkspace } from "@/components/assignments/workspace";
import { serverFetch } from "@/lib/api-server";
import type { SubjectPage } from "@/lib/types";

export default async function AssignmentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const response = await serverFetch("/subjects?limit=100");
  const subjects = response.ok ? ((await response.json()) as SubjectPage).items : [];
  return <AssignmentWorkspace assignmentId={encodeURIComponent(id)} subjects={subjects} />;
}
