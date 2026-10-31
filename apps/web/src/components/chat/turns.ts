import type { AgentRoute, AgentStep, AnswerFeedback, ChatCard, ConversationDetail, Source } from "@/lib/types";

export type Turn = {
  key: string;
  /** The saved message's id (null while an answer is still being written). */
  messageId: string | null;
  role: "user" | "assistant";
  text: string;
  /** Questions the answer suggests asking next, and a clarifying question with its options. */
  followups: string[];
  choices: { question: string; options: string[] } | null;
  /** The student's own thumbs up/down on this answer. */
  feedback: AnswerFeedback | null;
  /** True when this answer replaced an earlier one (the student asked again). */
  replaced: boolean;
  sources: Source[];
  error: string | null;
  stopped: boolean;
  streaming: boolean;
  degraded: boolean;
  /** True once the search of the student's materials has finished. */
  searched: boolean;
  /** True when the server removed something unsafe (an image, a script, a tracking link). */
  cleaned?: boolean;
  /** The text of each model turn, by turn number. A turn that ended in tool calls is retracted
   *  (`discarded`), so the visible answer is only the turns that were not. */
  parts: Record<number, string>;
  discarded: number[];
  route: AgentRoute | null;
  steps: AgentStep[];
  cards: ChatCard[];
};

export function assemble(parts: Record<number, string>, discarded: number[]): string {
  return Object.keys(parts)
    .map(Number)
    .sort((a, b) => a - b)
    .filter((turn) => !discarded.includes(turn))
    .map((turn) => parts[turn])
    .join("");
}

/** Proposals still waiting for an answer lapse when the student writes something else. */
export function expirePending(turns: Turn[]): Turn[] {
  const waiting = (turn: Turn) => turn.cards.some((c) => c.kind === "calendar_proposal" && c.data.status === "pending");
  if (!turns.some(waiting)) return turns;
  return turns.map((turn) =>
    waiting(turn)
      ? {
          ...turn,
          cards: turn.cards.map((c) =>
            c.kind === "calendar_proposal" && c.data.status === "pending"
              ? ({ kind: "calendar_proposal", data: { ...c.data, status: "expired" } } as ChatCard)
              : c,
          ),
        }
      : turn,
  );
}

export function newTurn(role: Turn["role"], text: string, streaming: boolean): Turn {
  return {
    key: nextKey(),
    messageId: null,
    role,
    text,
    followups: [],
    choices: null,
    feedback: null,
    replaced: false,
    sources: [],
    error: null,
    stopped: false,
    streaming,
    degraded: false,
    searched: !streaming,
    parts: {},
    discarded: [],
    route: null,
    steps: [],
    cards: [],
  };
}

const PROVIDER_PREF = "mindnest.chat.provider";

export function readPreferredProvider(): string | null {
  try {
    return window.localStorage.getItem(PROVIDER_PREF);
  } catch {
    return null;
  }
}

export function rememberProvider(id: string): void {
  try {
    window.localStorage.setItem(PROVIDER_PREF, id);
  } catch {
    // Storage can be blocked; the choice then simply is not remembered.
  }
}

let counter = 0;
const nextKey = () => `turn-${++counter}`;

export function turnsFrom(detail: ConversationDetail): Turn[] {
  return detail.messages.map((message) => {
    let text = "";
    let sources: Source[] = [];
    let error: string | null = null;
    let stopped = false;
    let route: AgentRoute | null = null;
    let steps: AgentStep[] = [];
    let followups: string[] = [];
    let choices: Turn["choices"] = null;
    const cards: ChatCard[] = [];
    for (const block of message.blocks) {
      if (block.type === "text") text += block.text;
      else if (block.type === "sources") sources = block.items;
      else if (block.type === "error") error = block.code;
      else if (block.type === "stopped") stopped = true;
      else if (block.type === "followups") followups = block.items;
      else if (block.type === "choices") choices = { question: block.question, options: block.options };
      else if (block.type === "steps") {
        steps = block.items;
        route = block.route;
      } else if (block.type === "card") cards.push({ kind: block.kind, data: block.data } as ChatCard);
    }
    return {
      key: message.id,
      messageId: message.id,
      role: message.role,
      text,
      followups,
      choices,
      feedback: message.feedback ?? null,
      replaced: Boolean(message.replaces_id),
      sources,
      error,
      stopped,
      streaming: false,
      degraded: false,
      searched: true,
      parts: {},
      discarded: [],
      route,
      steps,
      cards,
    };
  });
}

export function citedNumbers(text: string, sources: Source[]): number[] {
  const valid = new Set(sources.map((source) => source.n));
  const found = new Set<number>();
  for (const match of text.matchAll(/\[(\d{1,2})\]/g)) {
    const n = Number(match[1]);
    if (valid.has(n)) found.add(n);
  }
  return [...found].sort((a, b) => a - b);
}
