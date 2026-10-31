"use client";

import clsx from "clsx";
import { Download, FileStack, Menu, PanelRight, Sparkles } from "lucide-react";
import { motion } from "motion/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { DecideFn } from "@/components/chat-cards";
import { Composer } from "@/components/chat/composer";
import { HistoryPane } from "@/components/chat/history-pane";
import { AssistantMessage, UserMessage } from "@/components/chat/message";
import { SourcePanel } from "@/components/chat/source-panel";
import {
  assemble,
  expirePending,
  newTurn,
  readPreferredProvider,
  rememberProvider,
  turnsFrom,
  type Turn,
} from "@/components/chat/turns";
import { ConfirmDialog } from "@/components/kit/confirm";
import { ButtonLink } from "@/components/kit/button";
import { useToast } from "@/components/kit/toast";
import { Stagger, StaggerItem } from "@/components/motion/reveal";
import { Alert } from "@/components/ui";
import { useT } from "@/i18n/client";
import { scopeLabel } from "@/components/chat/scope-picker";
import { ApiError, api, streamChat, streamDecision, uploadChatAttachment } from "@/lib/api";
import {
  MAX_ATTACHMENTS,
  chatError,
  courseScope,
  scopeBody,
  scopeOf,
  type ScopeValue,
} from "@/lib/chat";
import { errorMessage, llmErrorText } from "@/lib/errors";
import type {
  AnswerFeedback,
  CalendarEdits,
  ChatAttachment,
  ChatEvent,
  Conversation,
  ConversationDetail,
  FeedbackReason,
  Provider,
  Subject,
} from "@/lib/types";

const EASE: [number, number, number, number] = [0.22, 1, 0.36, 1];
const HISTORY_SHEET =
  "glass-strong absolute inset-y-0 left-0 z-30 block w-[min(20rem,88vw)] overflow-hidden rounded-3xl";

/** The learning workspace: conversation history on the left, the conversation in the middle, and
 *  (when a citation is inspected) the source passage and file on the right. */
export function ChatWorkspace({
  subjects,
  initialConversationId,
  courseId,
  embedded = false,
}: {
  subjects: Subject[];
  initialConversationId: string | null;
  /** The course picked in the sidebar; new conversations start in it. */
  courseId: string | null;
  /** True inside the "Ask AI" side panel on another page: the history is a sheet, the sources open
   *  over the conversation, and the address bar is left alone. */
  embedded?: boolean;
}) {
  const t = useT();
  const toast = useToast();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [providers, setProviders] = useState<Provider[] | null>(null);
  const [providerId, setProviderId] = useState("");
  const [model, setModel] = useState("");
  const [liveModels, setLiveModels] = useState<string[]>([]);
  const [scope, setScope] = useState<ScopeValue>(() => courseScope(courseId));
  const [attachments, setAttachments] = useState<ChatAttachment[]>([]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inspect, setInspect] = useState<{ key: string; n: number } | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [toDelete, setToDelete] = useState<Conversation | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const pending = useRef<Record<number, string>>({});
  const frame = useRef<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  // While an answer is being written again: the turns to go back to if it does not finish.
  const regen = useRef<{ previous: Turn[]; done: boolean; error: string | null } | null>(null);

  const configured = useMemo(() => (providers ?? []).filter((p) => p.configured), [providers]);
  const noKey = providers !== null && configured.length === 0;
  const hasMessages = turns.length > 0;
  const active = conversations.find((c) => c.id === activeId) ?? null;
  const scopeSubject = scope.kind === "subject" ? (subjects.find((s) => s.id === scope.subjectId) ?? null) : null;

  const chooseProvider = useCallback((id: string, list: Provider[], preferredModel?: string | null) => {
    const provider = list.find((p) => p.id === id);
    if (!provider) return;
    setProviderId(id);
    setModel(preferredModel || provider.model || provider.default_model);
  }, []);

  const refreshConversations = useCallback(async () => {
    try {
      setConversations(await api<Conversation[]>("/conversations"));
    } catch {
      // The list is a convenience; the chat itself still works without it.
    } finally {
      setListLoading(false);
    }
  }, []);

  const loadConversation = useCallback(
    async (id: string, list: Provider[] | null) => {
      try {
        const detail = await api<ConversationDetail>(`/conversations/${id}`);
        setActiveId(detail.id);
        setTurns(turnsFrom(detail));
        setScope(scopeOf(detail));
        setAttachments([]);
        void api<ChatAttachment[]>(`/conversations/${detail.id}/attachments`)
          .then(setAttachments)
          .catch(() => {
            // The chips are a convenience; the conversation itself still opens.
          });
        setError(null);
        setInspect(null);
        stick.current = true;
        if (!embedded) window.history.replaceState(null, "", `/chat?c=${detail.id}`);
        const available = (list ?? []).filter((p) => p.configured);
        if (detail.provider && available.some((p) => p.id === detail.provider)) {
          chooseProvider(detail.provider, available, detail.model);
        }
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404) {
          if (!embedded) window.history.replaceState(null, "", "/chat");
        } else {
          setError(errorMessage(caught, t));
        }
      }
    },
    [chooseProvider, embedded, t],
  );

  // First load: conversations, providers and (if the address names one) that conversation.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      let list: Provider[] = [];
      try {
        list = await api<Provider[]>("/settings/providers");
      } catch (caught) {
        if (!cancelled) setError(errorMessage(caught, t));
      }
      if (cancelled) return;
      setProviders(list);
      const available = list.filter((p) => p.configured);
      const preferred = readPreferredProvider();
      const first = available.find((p) => p.id === preferred) ?? available[0];
      if (first) chooseProvider(first.id, available);
      await refreshConversations();
      if (initialConversationId) await loadConversation(initialConversationId, list);
    })();
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
    // Runs once on purpose: later changes are driven by user actions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Picking another course in the sidebar moves a not-yet-started conversation to it.
  useEffect(() => {
    if (!activeId && turns.length === 0) setScope(courseScope(courseId));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  // Files being read are checked again until they are ready (or have failed).
  const reading = attachments.some((a) => a.status === "uploaded" || a.status === "processing");
  useEffect(() => {
    if (!reading || !activeId) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      api<ChatAttachment[]>(`/conversations/${activeId}/attachments`)
        .then((rows) => {
          if (!cancelled) setAttachments(rows);
        })
        .catch(() => {
          // The next check tries again.
        });
    }, 1500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [reading, activeId]);

  // Ask the provider which models this key can use, so the suggestions are never out of date.
  useEffect(() => {
    setLiveModels([]);
    if (!providerId) return;
    let cancelled = false;
    api<{ models: string[] }>(`/settings/providers/${providerId}/models`)
      .then((result) => {
        if (!cancelled) setLiveModels(result.models);
      })
      .catch(() => {
        // Suggestions are optional; the typed model name still works.
      });
    return () => {
      cancelled = true;
    };
  }, [providerId]);

  useEffect(() => {
    if (stick.current) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [turns]);

  // Diagrams and formulas finish drawing after the text, which makes the list taller; stay at the
  // bottom while the student has not scrolled up.
  const listRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const list = listRef.current;
    if (!list || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      if (stick.current) bottomRef.current?.scrollIntoView({ block: "end" });
    });
    observer.observe(list);
    return () => observer.disconnect();
  }, [hasMessages]);

  const flush = useCallback(() => {
    if (frame.current !== null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
    }
    const chunk = pending.current;
    if (Object.keys(chunk).length === 0) return;
    pending.current = {};
    setTurns((previous) => {
      const last = previous[previous.length - 1];
      if (!last || last.role !== "assistant") return previous;
      const parts = { ...last.parts };
      for (const [turn, text] of Object.entries(chunk)) parts[Number(turn)] = (parts[Number(turn)] ?? "") + text;
      return [...previous.slice(0, -1), { ...last, parts, text: assemble(parts, last.discarded) }];
    });
  }, []);

  const updateLast = useCallback((patch: Partial<Turn>) => {
    setTurns((previous) => {
      const last = previous[previous.length - 1];
      if (!last || last.role !== "assistant") return previous;
      return [...previous.slice(0, -1), { ...last, ...patch }];
    });
  }, []);

  const handleEvent = useCallback(
    (event: ChatEvent) => {
      if (event.event === "meta") {
        const { title } = event.data;
        if (title) {
          setConversations((previous) =>
            previous.map((c) => (c.id === event.data.conversation_id ? { ...c, title } : c)),
          );
        }
      } else if (event.event === "sources") {
        updateLast({ sources: event.data.items, degraded: event.data.degraded, searched: true });
      } else if (event.event === "route") {
        updateLast({ route: event.data });
      } else if (event.event === "step") {
        // The same step is sent again when it finishes, so it is replaced, not added.
        const step = event.data;
        setTurns((previous) => {
          const last = previous[previous.length - 1];
          if (!last || last.role !== "assistant") return previous;
          const exists = last.steps.some((s) => s.id === step.id);
          const steps = exists ? last.steps.map((s) => (s.id === step.id ? step : s)) : [...last.steps, step];
          return [...previous.slice(0, -1), { ...last, steps }];
        });
      } else if (event.event === "card") {
        setTurns((previous) => {
          const last = previous[previous.length - 1];
          if (!last || last.role !== "assistant") return previous;
          return [...previous.slice(0, -1), { ...last, cards: [...last.cards, event.data] }];
        });
      } else if (event.event === "card_update") {
        // A proposal shown earlier was approved, declined or failed: settle that card.
        const update = event.data;
        const holds = (turn: Turn) =>
          turn.cards.some((c) => c.kind === "calendar_proposal" && c.data.proposal_id === update.proposal_id);
        setTurns((previous) =>
          previous.map((turn) =>
            holds(turn)
              ? {
                  ...turn,
                  cards: turn.cards.map((c) =>
                    c.kind === "calendar_proposal" && c.data.proposal_id === update.proposal_id
                      ? ({ kind: "calendar_proposal", data: { ...c.data, ...update } } as typeof c)
                      : c,
                  ),
                }
              : turn,
          ),
        );
      } else if (event.event === "discard") {
        // That model turn only asked for a tool; what it wrote is not part of the answer.
        flush();
        setTurns((previous) => {
          const last = previous[previous.length - 1];
          if (!last || last.role !== "assistant") return previous;
          const discarded = [...last.discarded, event.data.turn];
          return [...previous.slice(0, -1), { ...last, discarded, text: assemble(last.parts, discarded) }];
        });
      } else if (event.event === "token") {
        const turn = event.data.turn ?? 0;
        pending.current[turn] = (pending.current[turn] ?? "") + event.data.text;
        if (frame.current === null) frame.current = requestAnimationFrame(flush);
      } else if (event.event === "safety") {
        // The server removed something unsafe from the answer; show the cleaned text instead.
        flush();
        updateLast({ text: event.data.text, parts: { 0: event.data.text }, discarded: [], cleaned: true });
      } else if (event.event === "final") {
        // The finished answer: the server has checked the diagrams and citations and cut the
        // follow-up / choice block off the end, so this text replaces what was streamed.
        flush();
        updateLast({
          text: event.data.text,
          parts: { 0: event.data.text },
          discarded: [],
          followups: event.data.followups,
          choices: event.data.choices,
        });
      } else if (event.event === "error") {
        flush();
        if (regen.current) regen.current.error = event.data.code;
        updateLast({ error: event.data.code, streaming: false });
      } else if (event.event === "done") {
        flush();
        if (regen.current && event.data.message_id) regen.current.done = true;
        updateLast({
          streaming: false,
          ...(event.data.message_id ? { messageId: event.data.message_id } : {}),
          ...(event.data.replaces ? { replaced: true } : {}),
        });
      }
    },
    [flush, updateLast],
  );

  /** Start the conversation now (before the first message) when it does not exist yet. */
  const ensureConversation = useCallback(async (): Promise<string> => {
    if (activeId) return activeId;
    const created = await api<Conversation>("/conversations", {
      method: "POST",
      body: { subject_id: scope.kind === "subject" ? scope.subjectId : null },
    });
    let conversation = created;
    if (scope.kind === "materials") {
      conversation = await api<Conversation>(`/conversations/${created.id}/scope`, {
        method: "PATCH",
        body: scopeBody(scope),
      });
    }
    setActiveId(conversation.id);
    setConversations((previous) => [conversation, ...previous]);
    if (!embedded) window.history.replaceState(null, "", `/chat?c=${conversation.id}`);
    return conversation.id;
  }, [activeId, embedded, scope]);

  /** Write the answer: `override` is a follow-up or an option the student tapped; `regenerateOf`
   *  is the answer to be written again. */
  const send = useCallback(
    async (override?: string, regenerateOf?: string) => {
      const content = (override ?? input).trim();
      if (!content || streaming || !providerId) return;
      if (attachments.some((a) => a.status === "uploaded" || a.status === "processing")) {
        setError(t("chx.attach.wait"));
        return;
      }
      setError(null);
      setStreaming(true);
      stick.current = true;
      const controller = new AbortController();
      abortRef.current = controller;
      const fromBox = override === undefined && regenerateOf === undefined;

      try {
        const conversationId = await ensureConversation();
        rememberProvider(providerId);
        if (fromBox) setInput("");
        setInspect(null);
        if (regenerateOf) {
          // The old answer is put back if the new one does not finish.
          regen.current = { previous: turns, done: false, error: null };
          setTurns((previous) => [...previous.slice(0, -1), newTurn("assistant", "", true)]);
        } else {
          setTurns((previous) => [...expirePending(previous), newTurn("user", content, false), newTurn("assistant", "", true)]);
        }
        await streamChat(
          conversationId,
          { content, provider: providerId, model: model.trim() || undefined, regenerate_of: regenerateOf },
          handleEvent,
          controller.signal,
        );
      } catch (caught) {
        flush();
        const stopped = caught instanceof DOMException && caught.name === "AbortError";
        if (regen.current) {
          if (!stopped) setError(chatError(caught, t));
        } else if (stopped) {
          updateLast({ stopped: true, streaming: false });
        } else {
          // The request was refused or the connection dropped. Drop the empty answer slot and
          // give the question back to the box so nothing the student typed is lost.
          setTurns((previous) => {
            const last = previous[previous.length - 1];
            if (last?.role === "assistant" && !last.text) return previous.slice(0, -2);
            return previous;
          });
          if (fromBox) setInput((current) => current || content);
          setError(chatError(caught, t));
        }
      } finally {
        flush();
        const attempt = regen.current;
        regen.current = null;
        if (attempt && !attempt.done) {
          // Nothing was saved, so the earlier answer is still the answer.
          setTurns(attempt.previous);
          if (attempt.error) setError(llmErrorText(attempt.error, t));
        } else {
          updateLast({ streaming: false });
        }
        setStreaming(false);
        abortRef.current = null;
        void refreshConversations();
      }
    },
    [attachments, ensureConversation, flush, handleEvent, input, model, providerId, refreshConversations, streaming, t, turns, updateLast],
  );

  /** Write the newest answer again, from the same question. */
  const regenerate = useCallback(() => {
    const last = turns[turns.length - 1];
    const question = turns[turns.length - 2];
    if (!last || last.role !== "assistant" || !last.messageId || !question || question.role !== "user") return;
    void send(question.text, last.messageId);
  }, [send, turns]);

  const rate = useCallback(
    async (turnKey: string, rating: AnswerFeedback["rating"], reason: FeedbackReason | null, comment: string) => {
      const target = turns.find((turn) => turn.key === turnKey);
      if (!target?.messageId) return;
      await api(`/messages/${target.messageId}/feedback`, { method: "PUT", body: { rating, reason, comment } });
      setTurns((previous) =>
        previous.map((turn) => (turn.key === turnKey ? { ...turn, feedback: { rating, reason } } : turn)),
      );
    },
    [turns],
  );

  const withdraw = useCallback(
    async (turnKey: string) => {
      const target = turns.find((turn) => turn.key === turnKey);
      if (!target?.messageId) return;
      await api(`/messages/${target.messageId}/feedback`, { method: "DELETE" });
      setTurns((previous) => previous.map((turn) => (turn.key === turnKey ? { ...turn, feedback: null } : turn)));
    },
    [turns],
  );

  /** Choose what the chat may search. For a conversation that already exists it is saved at once. */
  const applyScope = useCallback(
    async (next: ScopeValue) => {
      const before = scope;
      setScope(next);
      if (!activeId) return;
      try {
        const updated = await api<Conversation>(`/conversations/${activeId}/scope`, {
          method: "PATCH",
          body: scopeBody(next),
        });
        setConversations((previous) => previous.map((c) => (c.id === updated.id ? { ...c, ...updated } : c)));
      } catch (caught) {
        setScope(before);
        setError(chatError(caught, t));
      }
    },
    [activeId, scope, t],
  );

  const attach = useCallback(
    async (files: File[]) => {
      if (streaming || files.length === 0) return;
      setError(null);
      if (attachments.length + files.length > MAX_ATTACHMENTS) {
        setError(t("chx.err.too_many_attachments"));
        return;
      }
      let conversationId: string;
      try {
        conversationId = await ensureConversation();
      } catch (caught) {
        setError(chatError(caught, t));
        return;
      }
      for (const file of files) {
        try {
          const added = await uploadChatAttachment(conversationId, file);
          setAttachments((previous) => [...previous, added]);
        } catch (caught) {
          setError(`${file.name}: ${chatError(caught, t)}`);
        }
      }
    },
    [attachments.length, ensureConversation, streaming, t],
  );

  async function removeAttachment(attachment: ChatAttachment) {
    if (!activeId) return;
    try {
      await api(`/conversations/${activeId}/attachments/${attachment.id}`, { method: "DELETE" });
      setAttachments((previous) => previous.filter((a) => a.id !== attachment.id));
    } catch (caught) {
      setError(chatError(caught, t));
    }
  }

  /** The student's answer to a proposal card (approve, edit-and-approve, cancel). The rest of the
   *  answer streams into the same message. A failure is thrown so the card can show it. */
  const decide = useCallback<DecideFn>(
    async (runId: string, decision: "approve" | "reject", edits?: CalendarEdits) => {
      if (!activeId || streaming) return;
      setError(null);
      setStreaming(true);
      stick.current = true;
      const controller = new AbortController();
      abortRef.current = controller;
      updateLast({ streaming: true, error: null, stopped: false });
      try {
        await streamDecision(activeId, runId, { decision, edits }, handleEvent, controller.signal);
      } catch (caught) {
        flush();
        if (caught instanceof DOMException && caught.name === "AbortError") {
          updateLast({ stopped: true });
        } else {
          if (caught instanceof ApiError && caught.code === "approval_expired") {
            setTurns((previous) => expirePending(previous));
          }
          throw caught;
        }
      } finally {
        flush();
        updateLast({ streaming: false });
        setStreaming(false);
        abortRef.current = null;
      }
    },
    [activeId, flush, handleEvent, streaming, updateLast],
  );

  function newChat() {
    abortRef.current?.abort();
    setActiveId(null);
    setTurns([]);
    setError(null);
    setInspect(null);
    setScope(courseScope(courseId));
    setAttachments([]);
    setListOpen(false);
    if (!embedded) window.history.replaceState(null, "", "/chat");
  }

  async function confirmDelete() {
    const target = toDelete;
    if (!target) return;
    try {
      await api(`/conversations/${target.id}`, { method: "DELETE" });
      setConversations((previous) => previous.filter((c) => c.id !== target.id));
      if (target.id === activeId) newChat();
    } catch (caught) {
      setError(errorMessage(caught, t));
    }
  }

  async function rename(conversation: Conversation, title: string) {
    try {
      const updated = await api<Conversation>(`/conversations/${conversation.id}`, { method: "PATCH", body: { title } });
      setConversations((previous) => previous.map((c) => (c.id === updated.id ? { ...c, title: updated.title } : c)));
    } catch {
      toast.error(t("cw.renameFailed"));
    }
  }

  function exportMarkdown() {
    const lines = [`# ${active?.title ?? t("chat.new")}`, ""];
    for (const turn of turns) {
      lines.push(`## ${turn.role === "user" ? t("cw.you") : t("cw.assistant")}`, "", turn.text, "");
      if (turn.role === "assistant" && turn.sources.length > 0) {
        lines.push(`**${t("cw.sources")}**`, "");
        for (const source of turn.sources) {
          lines.push(`${source.n}. ${source.filename}${source.page !== null ? ` — ${t("chat.page", { n: source.page })}` : ""}`);
        }
        lines.push("");
      }
    }
    const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${(active?.title ?? "conversation").replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "") || "conversation"}.md`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 2000);
  }

  const onCite = useCallback(
    (turnKey: string, n: number) =>
      setInspect((current) => (current?.key === turnKey && current.n === n ? null : { key: turnKey, n })),
    [],
  );

  const inspected = inspect ? turns.find((turn) => turn.key === inspect.key) : undefined;
  const lastWithSources = [...turns].reverse().find((turn) => turn.role === "assistant" && turn.sources.length > 0);
  const docCount =
    scope.kind === "materials"
      ? scope.materialIds.length
      : (scopeSubject?.material_count ?? subjects.reduce((sum, s) => sum + s.material_count, 0));
  const courseLabel = scopeSubject?.name ?? t("cw.thisCourse");

  const starters = [
    t("cw.starter.summary", { course: courseLabel }),
    t("cw.starter.explain", { course: courseLabel }),
    t("cw.starter.quiz", { course: courseLabel }),
    t("cw.starter.plan"),
  ];

  const panel = inspected ? (
    <SourcePanel
      sources={inspected.sources}
      activeN={inspect?.n ?? 1}
      subjects={subjects}
      onSelect={(n) => setInspect({ key: inspected.key, n })}
      onClose={() => setInspect(null)}
    />
  ) : null;

  return (
    <div className={clsx("relative flex h-full min-h-0", embedded ? "" : "gap-3 px-3 pb-3 pt-3 sm:px-6")}>
      {/* History */}
      <aside
        aria-label={t("cw.history")}
        className={
          listOpen ? HISTORY_SHEET : embedded ? "hidden" : "glass hidden w-72 shrink-0 overflow-hidden rounded-3xl lg:block"
        }
      >
        <HistoryPane
          conversations={conversations}
          loading={listLoading}
          activeId={activeId}
          subjects={subjects}
          courseId={courseId}
          onSelect={(conversation) => {
            setListOpen(false);
            void loadConversation(conversation.id, providers);
          }}
          onNew={newChat}
          onDelete={setToDelete}
          onRename={rename}
        />
      </aside>
      {listOpen ? (
        <button
          type="button"
          aria-label={t("common.close")}
          onClick={() => setListOpen(false)}
          className={clsx("absolute inset-0 z-20 bg-black/40 backdrop-blur-[2px]", !embedded && "lg:hidden")}
        />
      ) : null}

      {/* Conversation */}
      <section aria-label={t("nav.chat")} className={clsx("flex min-w-0 flex-1 flex-col", embedded ? "" : "glass rounded-3xl")}>
        <header className="flex h-14 shrink-0 items-center gap-2 border-b border-border px-4">
          <button
            type="button"
            onClick={() => setListOpen(true)}
            aria-label={t("chat.chatsToggle")}
            className={clsx("rounded-lg p-1.5 text-muted hover:bg-surface-3 hover:text-ink", !embedded && "lg:hidden")}
          >
            <Menu className="h-4 w-4" aria-hidden />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold leading-5">{active?.title ?? t("chat.new")}</h1>
            <p className="truncate text-xs leading-4 text-muted">
              {scopeLabel(scope, subjects, t)}
              {hasMessages ? ` · ${t("cw.messageCount", { count: turns.length })}` : ""}
            </p>
          </div>
          <button
            type="button"
            onClick={exportMarkdown}
            disabled={!hasMessages}
            title={t("cw.export")}
            aria-label={t("cw.export")}
            className="rounded p-1.5 text-muted hover:bg-surface-3 hover:text-ink disabled:opacity-40"
          >
            <Download className="h-4 w-4" aria-hidden />
          </button>
          <button
            type="button"
            onClick={() => {
              if (inspect) setInspect(null);
              else if (lastWithSources) setInspect({ key: lastWithSources.key, n: lastWithSources.sources[0].n });
            }}
            disabled={!inspect && !lastWithSources}
            aria-pressed={inspect !== null}
            title={t("cw.sourcesToggle")}
            aria-label={t("cw.sourcesToggle")}
            className={clsx(
              "rounded p-1.5 hover:bg-surface-3 hover:text-ink disabled:opacity-40",
              inspect ? "bg-surface-3 text-ink" : "text-muted",
            )}
          >
            <PanelRight className="h-4 w-4" aria-hidden />
          </button>
        </header>

        <div
          className="min-h-0 flex-1 overflow-y-auto"
          onScroll={(event) => {
            const el = event.currentTarget;
            stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
          }}
        >
          {!hasMessages ? (
            <div className="mx-auto flex min-h-full max-w-2xl flex-col justify-center px-4 py-8 sm:px-6">
              <span className="relative mb-5 flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-accent text-on-primary shadow-glow ring-1 ring-inset ring-white/25">
                <span aria-hidden className="absolute inset-0 -z-10 animate-glow-pulse rounded-2xl bg-primary/50 blur-xl" />
                <Sparkles className="h-6 w-6" aria-hidden />
              </span>
              <h2 className="font-display text-balance text-3xl leading-tight sm:text-4xl">
                {scopeSubject ? t("cw.empty.title", { course: scopeSubject.name }) : t("cw.empty.titleAll")}
              </h2>
              <p className="mt-2 text-sm text-muted">
                {docCount === 0
                  ? t("cw.empty.noDocs")
                  : scopeSubject
                    ? t("cw.empty.context", { count: docCount })
                    : t("cw.empty.contextAll")}
              </p>
              {docCount === 0 ? (
                <div className="mt-3">
                  <ButtonLink href={scopeSubject ? `/subjects/${scopeSubject.id}` : "/subjects"} size="sm" variant="secondary">
                    <FileStack className="h-3.5 w-3.5" aria-hidden />
                    {t("cw.empty.upload")}
                  </ButtonLink>
                </div>
              ) : null}
              {!noKey ? (
                <Stagger as="ul" inView={false} className="mt-7 grid gap-2.5 sm:grid-cols-2">
                  {starters.map((starter) => (
                    <StaggerItem as="li" key={starter} className="flex">
                      <button
                        type="button"
                        onClick={() => setInput(starter)}
                        className="glass-flat card-hover spot block w-full rounded-2xl px-4 py-3.5 text-left text-sm hover:text-brand"
                      >
                        {starter}
                      </button>
                    </StaggerItem>
                  ))}
                </Stagger>
              ) : null}
            </div>
          ) : (
            <ol ref={listRef} className="mx-auto flex max-w-3xl flex-col gap-7 px-4 py-6 sm:px-6">
              {turns.map((turn, index) => (
                <motion.li
                  key={turn.key}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, ease: EASE }}
                >
                  {turn.role === "user" ? (
                    <UserMessage text={turn.text} />
                  ) : (
                    <AssistantMessage
                      turn={turn}
                      activeSource={inspect?.key === turn.key ? inspect.n : null}
                      onCite={onCite}
                      onDecide={decide}
                      busy={streaming}
                      isLast={index === turns.length - 1}
                      onRegenerate={regenerate}
                      onAsk={(text) => void send(text)}
                      onRate={rate}
                      onWithdraw={withdraw}
                    />
                  )}
                </motion.li>
              ))}
            </ol>
          )}
          <div ref={bottomRef} />
        </div>

        <div className="shrink-0 px-3 pb-3 pt-1 sm:px-4 sm:pb-4">
          <div className="mx-auto max-w-3xl">
            {error ? (
              <div className="mb-2">
                <Alert>{error}</Alert>
              </div>
            ) : null}
            <Composer
              value={input}
              onChange={setInput}
              onSend={() => void send()}
              onStop={() => abortRef.current?.abort()}
              streaming={streaming}
              noKey={noKey}
              subjects={subjects}
              scope={scope}
              onScope={(next) => void applyScope(next)}
              attachments={attachments}
              onAttach={(files) => void attach(files)}
              onRemoveAttachment={(attachment) => void removeAttachment(attachment)}
              providers={configured}
              providerId={providerId}
              onProvider={(id) => chooseProvider(id, configured)}
              model={model}
              onModel={setModel}
              modelSuggestions={liveModels}
            />
            {!noKey ? <p className="mt-1 hidden text-[11px] text-faint sm:block">{t("chat.hint")}</p> : null}
          </div>
        </div>
      </section>

      {/* Source inspector: a side pane on wide screens, a sheet over the conversation on narrow ones */}
      {panel ? (
        <>
          {embedded ? null : (
            <motion.div
              initial={{ opacity: 0, x: 28 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.35, ease: EASE }}
              className="glass-strong hidden w-[24rem] shrink-0 overflow-hidden rounded-3xl lg:block xl:w-[28rem]"
            >
              {panel}
            </motion.div>
          )}
          <div className={clsx("glass-strong absolute inset-0 z-30 overflow-hidden", embedded ? "" : "rounded-3xl lg:hidden")}>{panel}</div>
        </>
      ) : null}

      <ConfirmDialog
        open={toDelete !== null}
        title={t("chat.deleteChat")}
        description={t("chat.deleteConfirm")}
        confirmLabel={t("common.delete")}
        tone="danger"
        onConfirm={confirmDelete}
        onClose={() => setToDelete(null)}
      />
    </div>
  );
}
