import { QuizDetailView } from "@/components/quiz-detail-view";

export default async function QuizPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <QuizDetailView quizId={encodeURIComponent(id)} />;
}
