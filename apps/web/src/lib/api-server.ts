import { cookies } from "next/headers";

import type { User } from "./types";

// Unlike next.config rewrites, this is read at request time, so it follows the runtime env.
const API_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

/** Call the API from a Server Component, forwarding the visitor's cookies. */
export async function serverFetch(path: string): Promise<Response> {
  const cookieHeader = (await cookies()).toString();
  return fetch(`${API_URL}/api/v1${path}`, {
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
    cache: "no-store",
  });
}

/** The signed-in user, or null when signed out. API outages propagate as errors on purpose,
 *  so a down API shows an error page instead of silently looking like "signed out". */
export async function fetchMe(): Promise<User | null> {
  const response = await serverFetch("/auth/me");
  if (response.status === 401) return null;
  if (!response.ok) throw new Error(`Could not load the current user (HTTP ${response.status}).`);
  return (await response.json()) as User;
}

/** Which optional sign-in methods are switched on. Never throws: the sign-in page must still
 *  render (with email and password) when this cannot be answered. */
export async function fetchProviders(): Promise<{ google: boolean }> {
  try {
    const response = await serverFetch("/auth/providers");
    if (!response.ok) return { google: false };
    const body = (await response.json()) as { google?: boolean };
    return { google: body.google === true };
  } catch {
    return { google: false };
  }
}
