import { EvalDatasetView } from "@/components/eval-dataset-view";

export default async function EvalDatasetPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EvalDatasetView datasetId={encodeURIComponent(id)} />;
}
