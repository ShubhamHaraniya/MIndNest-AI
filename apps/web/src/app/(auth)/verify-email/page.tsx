import { VerifyEmail } from "@/components/auth-forms";

export default async function VerifyEmailPage({
  searchParams,
}: {
  searchParams: Promise<{ token?: string }>;
}) {
  const { token } = await searchParams;
  return <VerifyEmail token={token ?? null} />;
}
