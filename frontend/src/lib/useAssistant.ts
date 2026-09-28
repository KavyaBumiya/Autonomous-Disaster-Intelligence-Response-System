/**
 * Commander assistant conversation hook.
 *
 * Wraps `POST /api/command/query` with a stable `conversation_id` so the
 * backend can thread multi-turn history, and guarantees the message list never
 * gets stuck on a placeholder: whatever happens, the user always ends up with
 * an answer.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import { COMMAND_TIMEOUT_MS } from "./config";

/** Message shape consumed by the existing conversation UI. */
export interface AssistantMessage {
  who: "user" | "ai";
  text: string;
}

/** Generate a conversation id without assuming crypto.randomUUID exists. */
function newConversationId(): string {
  const cryptoApi = globalThis.crypto as Crypto | undefined;
  if (cryptoApi?.randomUUID) return cryptoApi.randomUUID();
  return `conv-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export interface AssistantState {
  messages: AssistantMessage[];
  input: string;
  setInput: (value: string) => void;
  isThinking: boolean;
  send: () => void;
  /** True when the last reply came from the AI rather than the offline path. */
  lastReplyFromAi: boolean;
}

export function useAssistant(
  initialMessages: AssistantMessage[],
  zoneId: string | null,
  onNotify: (message: string) => void,
): AssistantState {
  const [messages, setMessages] = useState<AssistantMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [isThinking, setThinking] = useState(false);
  const [lastReplyFromAi, setLastReplyFromAi] = useState(false);

  const conversationId = useRef<string>(newConversationId());
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const send = useCallback(() => {
    const query = input.trim();
    if (!query || isThinking) return;

    // Optimistic user turn, exactly as the console showed it before.
    setMessages((current) => [...current, { who: "user", text: query }]);
    setInput("");
    setThinking(true);

    const controller = new AbortController();
    abortRef.current = controller;

    void api
      .commandQuery(
        {
          user_query: query,
          conversation_id: conversationId.current,
          include_xai: true,
          zone_context: zoneId,
        },
        controller.signal,
      )
      .then((result) => {
        setMessages((current) => [
          ...current,
          { who: "ai", text: result.response?.trim() || "No response was returned." },
        ]);
        setLastReplyFromAi(result.ai_available);
        onNotify("AegisAI analyzed the live context");
      })
      .catch((error: unknown) => {
        const detail = error instanceof ApiError ? error.detail : "Backend unreachable";
        setMessages((current) => [
          ...current,
          {
            who: "ai",
            text: `I could not reach the AegisAI gateway (${detail}). The deterministic engines and data APIs are unaffected — retry, or ask again once connectivity is restored.`,
          },
        ]);
        setLastReplyFromAi(false);
        onNotify("AegisAI could not reach the backend");
      })
      .finally(() => {
        setThinking(false);
        abortRef.current = null;
      });
  }, [input, isThinking, onNotify, zoneId]);

  return { messages, input, setInput, isThinking, send, lastReplyFromAi };
}

/** Default timeout note surfaced in dev tooling. */
export const ASSISTANT_TIMEOUT_MS = COMMAND_TIMEOUT_MS;
