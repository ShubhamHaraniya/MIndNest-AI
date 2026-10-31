/** Browser-side API client. Requests go to this site's own /api path, which Next.js forwards
 *  to the FastAPI service, so the httpOnly session cookie travels automatically. */

import type { CalendarEdits, ChatAttachment, ChatEvent, Material, MaterialKind } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function send<T>(path: string, init: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, { credentials: "same-origin", ...init });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network", "Could not reach the server.");
  }

  if (response.status === 204) return undefined as T;

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    // Not JSON (for example a proxy error page); handled below.
  }

  if (!response.ok) {
    const envelope = (payload ?? {}) as { code?: string; message?: string; details?: unknown };
    throw new ApiError(
      response.status,
      envelope.code ?? `http_${response.status}`,
      envelope.message ?? "Request failed.",
      envelope.details,
    );
  }
  return payload as T;
}

type Options = {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
};

export function api<T = void>(path: string, options: Options = {}): Promise<T> {
  return send<T>(path, {
    method: options.method ?? "GET",
    headers: options.body === undefined ? undefined : { "Content-Type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });
}

/** Upload one file. The browser sets the multipart boundary itself, so no Content-Type here. */
export function uploadMaterial(subjectId: string, file: File, kind: MaterialKind, module?: string | null): Promise<Material> {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  if (module && module.trim()) form.append("module", module.trim());
  return send<Material>(`/subjects/${subjectId}/materials`, { method: "POST", body: form });
}

/** Attach one file to an assignment (it is stored in the assignment's course). */
export function uploadAssignmentFile(assignmentId: string, file: File): Promise<unknown> {
  const form = new FormData();
  form.append("file", file);
  return send<unknown>(`/assignments/${assignmentId}/files`, { method: "POST", body: form });
}

/** Attach one file (a PDF, Word file or picture of text) to a conversation. */
export function uploadChatAttachment(conversationId: string, file: File): Promise<ChatAttachment> {
  const form = new FormData();
  form.append("file", file);
  return send<ChatAttachment>(`/conversations/${conversationId}/attachments`, { method: "POST", body: form });
}

type ChatRequest = { content: string; provider?: string; model?: string; regenerate_of?: string };

/** Send a chat message and call `onEvent` for each streamed event as it arrives.
 *  Resolves when the stream ends; rejects with ApiError if the request itself is refused
 *  (for example no provider key yet). Aborting `signal` stops reading, and the server keeps
 *  whatever part of the answer it had already written. */
export function streamChat(
  conversationId: string,
  request: ChatRequest,
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  return streamPost(`/conversations/${conversationId}/messages`, request, onEvent, signal);
}

/** The student's answer to a proposal the chat paused on. The rest of the answer streams back
 *  the same way as a new message. Rejects with ApiError 409 `approval_expired` when it is too late. */
export function streamDecision(
  conversationId: string,
  runId: string,
  decision: { decision: "approve" | "reject"; edits?: CalendarEdits },
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  return streamPost(`/conversations/${conversationId}/runs/${runId}/decision`, decision, onEvent, signal);
}

async function streamPost(
  path: string,
  payload: unknown,
  onEvent: (event: ChatEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network", "Could not reach the server.");
  }

  if (!response.ok || !response.body) {
    let envelope: { code?: string; message?: string } = {};
    try {
      envelope = await response.json();
    } catch {
      // Not JSON; fall through to the generic code.
    }
    throw new ApiError(response.status, envelope.code ?? `http_${response.status}`, envelope.message ?? "Request failed.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary = buffer.indexOf("\n\n");
      while (boundary !== -1) {
        const raw = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const event = parseEvent(raw);
        if (event) onEvent(event);
        boundary = buffer.indexOf("\n\n");
      }
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "network", "The connection was interrupted.");
  }
}

function parseEvent(raw: string): ChatEvent | null {
  let name = "";
  let data = "";
  for (const line of raw.split("\n")) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) data += line.slice(5).trim();
  }
  if (!name || !data) return null;
  try {
    return { event: name, data: JSON.parse(data) } as unknown as ChatEvent;
  } catch {
    return null;
  }
}
