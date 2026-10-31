import { AttemptScreen } from "@/components/quizzes/attempt-screen";

export default async function QuizAttemptPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  // The key makes "take it again" start from a clean screen instead of reusing the old state.
  return <AttemptScreen key={id} attemptId={encodeURIComponent(id)} />;
}
