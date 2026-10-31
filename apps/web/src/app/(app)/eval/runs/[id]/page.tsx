import { EvalRunView } from "@/components/eval-run-view";

export default async function EvalRunPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvalRunView runId={encodeURIComponent(id)} />;
}
