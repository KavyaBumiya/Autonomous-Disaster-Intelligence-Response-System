/**
 * AEGIS-AI — Command Center
 * ==========================
 * Natural-language interface backed by the Groq AI Gateway.
 *
 * PRD §14 requirements implemented here:
 *   ✓ Live disaster map reference (link to dashboard)
 *   ✓ AI command / chat interface
 *   ✓ Evidence panel (XAI reasoning display)
 *   ✓ Approval queue (human gate — AI cannot approve)
 *   ✓ Function call transparency (shows which tools were invoked)
 *   ✓ Groq online / offline status indicator
 *   ✓ Quick-action buttons for common commander queries
 *
 * SECURITY: The Groq API key never reaches this component.
 *   Queries go to POST /api/command/query — the backend handles the key.
 */
import React, { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import {
  commandApi,
  actionsApi,
  apiErrorMessage,
  type CommandResponse,
  type Action,
} from "@/services/api";
import { ApprovalQueue }  from "@/components/ApprovalQueue";
import { EvidencePanel }  from "@/components/EvidencePanel";
import { SystemStatus }   from "@/components/SystemStatus";

// ── Types ─────────────────────────────────────────────────────────────────

interface ChatMessage {
  id:           string;
  role:         "user" | "assistant" | "system";
  content:      string;
  timestamp:    Date;
  functionCalls?: { name: string; arguments: Record<string, unknown> }[];
  executionResults?: Record<string, unknown>[];
  groqCallId?:  string;
  modelUsed?:   string;
  isError?:     boolean;
}

// ── Helpers ───────────────────────────────────────────────────────────────

function msgId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const PRIORITY_COLOURS: Record<string, string> = {
  CRITICAL: "text-[#ff6b6b]",
  HIGH:     "text-[#f3b562]",
  MEDIUM:   "text-yellow-300",
  LOW:      "text-[#38d9c4]",
};

const QUICK_ACTIONS = [
  { label: "Critical incidents",    query: "Show me all critical incidents above priority 70." },
  { label: "Available resources",   query: "List all available rescue teams and vehicles." },
  { label: "Summarise top incident", query: "Summarise the highest-priority active incident." },
  { label: "Flood +30% rainfall",   query: "What happens if rainfall increases by 30%? Run a what-if simulation for the active flood zone." },
  { label: "Safest route",          query: "Show me the safest route for Team Bravo to the highest-priority zone." },
  { label: "Approval queue",        query: "How many actions are awaiting my approval?" },
  { label: "Why critical?",         query: "Why is the highest-priority zone marked CRITICAL? Explain the evidence." },
];

// ── Component ─────────────────────────────────────────────────────────────

export const CommandCenter: React.FC = () => {
  const navigate     = useNavigate();
  const queryClient  = useQueryClient();
  const chatEndRef   = useRef<HTMLDivElement>(null);
  const inputRef     = useRef<HTMLInputElement>(null);

  const [messages,     setMessages]     = useState<ChatMessage[]>([]);
  const [inputValue,   setInputValue]   = useState("");
  const [activePanel,  setActivePanel]  = useState<"chat" | "evidence" | "approvals">("chat");
  const [selectedIncidentId, setSelectedIncidentId] = useState<string | null>(null);

  // Stable multi-turn conversation id (Redis-backed on the backend, PRD §11)
  const [conversationId] = useState<string>(
    () => `cmd-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
  );

  // ── Groq health check ───────────────────────────────────────────────────
  const { data: healthData } = useQuery({
    queryKey: ["command-health"],
    queryFn:  () => commandApi.health().then((r) => r.data),
    refetchInterval: 30_000,
    retry: false,
  });
  const groqOnline = healthData?.groq_available ?? false;

  // ── Approval queue ──────────────────────────────────────────────────────
  const { data: queueData, refetch: refetchQueue } = useQuery({
    queryKey: ["approval-queue"],
    queryFn:  () => commandApi.approvalQueue().then((r) => r.data),
    refetchInterval: 15_000,
  });
  const pendingCount = queueData?.pending_count ?? 0;

  // ── Send query mutation ─────────────────────────────────────────────────
  const sendMutation = useMutation({
    mutationFn: (query: string) =>
      commandApi.query({
        user_query:     query,
        conversation_id: conversationId,
        include_xai:    true,
        zone_context:   undefined,
      }).then((r) => r.data),

    onMutate: (query) => {
      const userMsg: ChatMessage = {
        id:        msgId(),
        role:      "user",
        content:   query,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMsg]);
    },

    onSuccess: (data: CommandResponse) => {
      const assistantMsg: ChatMessage = {
        id:               msgId(),
        role:             "assistant",
        content:          data.response,
        timestamp:        new Date(),
        functionCalls:    data.function_calls,
        executionResults: data.execution_results,
        groqCallId:       data.groq_call_id,
        modelUsed:        data.model_used,
      };
      setMessages((prev) => [...prev, assistantMsg]);

      // If tools were called, surface a toast
      if (data.function_calls.length > 0) {
        const names = data.function_calls.map((f) => f.name).join(", ");
        toast.info(`Tools invoked: ${names}`, { duration: 3000 });
      }

      // If the query was about approvals, refresh the queue
      queryClient.invalidateQueries({ queryKey: ["approval-queue"] });
    },

    onError: (err) => {
      const errorMsg: ChatMessage = {
        id:        msgId(),
        role:      "assistant",
        content:   `⚠️ ${apiErrorMessage(err)}`,
        timestamp: new Date(),
        isError:   true,
      };
      setMessages((prev) => [...prev, errorMsg]);
      toast.error(apiErrorMessage(err));
    },
  });

  // Scroll to bottom when new message arrives
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const welcomeText = groqOnline
    ? `Groq AI Gateway ready (${healthData?.model ?? "qwen/qwen3.8-27b"}). Ask anything about active incidents, resources, predictions, or routing.`
    : "Running in offline mode — Groq AI unavailable. Deterministic engine and all data APIs are still operational. Type a query to see available data.";

  // ── Handlers ─────────────────────────────────────────────────────────────

  const handleSend = useCallback(() => {
    const query = inputValue.trim();
    if (!query || sendMutation.isPending) return;
    setInputValue("");
    sendMutation.mutate(query);
  }, [inputValue, sendMutation]);

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // ── Approve / Reject action ───────────────────────────────────────────

  const approveMutation = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "approved" | "rejected" }) =>
      actionsApi.updateStatus(id, status),
    onSuccess: (_, { status }) => {
      toast.success(`Action ${status}`);
      refetchQueue();
      queryClient.invalidateQueries({ queryKey: ["approval-queue"] });
    },
    onError: (err) => toast.error(apiErrorMessage(err)),
  });

  // ── Render ────────────────────────────────────────────────────────────

  return (
    <div className="ops-shell min-h-screen text-white">
      {/* ── Nav ──────────────────────────────────────────────────────────── */}
      <header className="ops-nav sticky top-0 z-20">
        <div className="ops-container nav-wide flex min-h-[68px] items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <button
              onClick={() => navigate("/")}
              className="grid h-9 w-9 place-items-center rounded-xl bg-[#38d9c4] text-sm font-bold text-[#07101c] transition hover:opacity-90"
              aria-label="Back to dashboard"
            >
              ←
            </button>
            <div>
              <div className="text-base font-bold tracking-tight">
                AegisAI <span className="font-normal text-slate-400">/ command center</span>
              </div>
              <div className="ops-kicker">AI-assisted incident command</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {/* Pending approvals badge */}
            {pendingCount > 0 && (
              <button
                onClick={() => setActivePanel("approvals")}
                className="flex items-center gap-1.5 rounded-lg bg-[#f3b562]/20 px-3 py-1.5 text-xs font-semibold text-[#f3b562] transition hover:bg-[#f3b562]/30"
              >
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#f3b562] opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-[#f3b562]" />
                </span>
                {pendingCount} pending approval{pendingCount !== 1 ? "s" : ""}
              </button>
            )}

            <SystemStatus groqOnline={groqOnline} groqModel={healthData?.model} />
          </div>
        </div>
      </header>

      <div className="ops-container py-6">
        {/* ── Panel tabs ──────────────────────────────────────────────── */}
        <div className="mb-5 flex gap-1 rounded-xl border border-white/10 bg-white/[.03] p-1">
          {(["chat", "evidence", "approvals"] as const).map((panel) => (
            <button
              key={panel}
              onClick={() => setActivePanel(panel)}
              className={`flex-1 rounded-lg py-2 text-sm font-medium capitalize transition ${
                activePanel === panel
                  ? "bg-[#38d9c4] text-[#07101c]"
                  : "text-slate-400 hover:text-white"
              }`}
            >
              {panel === "approvals"
                ? `Human Approval Gate${pendingCount > 0 ? ` (${pendingCount})` : ""}`
                : panel === "evidence"
                ? "XAI Evidence"
                : "AI Command"}
            </button>
          ))}
        </div>

        {/* ── Chat panel ───────────────────────────────────────────────── */}
        {activePanel === "chat" && (
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_320px]">
            {/* Chat column */}
            <div className="flex flex-col gap-4">
              {/* Message thread */}
              <div className="ops-panel flex h-[520px] flex-col overflow-hidden">
                <div className="ops-panel-header shrink-0">
                  <div>
                    <div className="ops-kicker">Groq AI Gateway</div>
                    <div className="ops-title">Commander interface</div>
                  </div>
                  <span className={`ops-mono text-xs ${groqOnline ? "text-[#38d9c4]" : "text-[#f3b562]"}`}>
                    {groqOnline ? "● LIVE" : "○ OFFLINE"}
                  </span>
                </div>

                <div className="flex-1 space-y-3 overflow-y-auto p-4">
                  {messages.length === 0 && (
                    <div className="rounded-lg border border-white/10 bg-white/[.03] p-4 text-sm text-slate-400">
                      {welcomeText}
                    </div>
                  )}
                  {messages.map((msg) => (
                    <ChatBubble
                      key={msg.id}
                      msg={msg}
                      onSelectIncident={(id) => {
                        setSelectedIncidentId(id);
                        setActivePanel("evidence");
                      }}
                    />
                  ))}
                  {sendMutation.isPending && (
                    <div className="flex items-center gap-2 text-slate-400">
                      <span className="inline-flex gap-1">
                        {[0, 1, 2].map((i) => (
                          <span
                            key={i}
                            className="h-1.5 w-1.5 animate-bounce rounded-full bg-[#38d9c4]"
                            style={{ animationDelay: `${i * 0.15}s` }}
                          />
                        ))}
                      </span>
                      <span className="text-xs">Querying Groq…</span>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>

                {/* Input bar */}
                <div className="shrink-0 border-t border-white/10 p-3">
                  <div className="flex gap-2">
                    <input
                      ref={inputRef}
                      type="text"
                      value={inputValue}
                      onChange={(e) => setInputValue(e.target.value)}
                      onKeyDown={handleKey}
                      placeholder={
                        groqOnline
                          ? "Ask anything — incidents, resources, predictions, routes…"
                          : "Groq offline — queries will use deterministic fallback"
                      }
                      disabled={sendMutation.isPending}
                      className="flex-1 rounded-lg border border-white/10 bg-white/[.05] px-3 py-2 text-sm text-white placeholder-slate-500 outline-none transition focus:border-[#38d9c4]/60 focus:ring-1 focus:ring-[#38d9c4]/30 disabled:opacity-50"
                      autoFocus
                    />
                    <button
                      onClick={handleSend}
                      disabled={sendMutation.isPending || !inputValue.trim()}
                      className="ops-button-primary rounded-lg px-4 py-2 text-sm disabled:opacity-40"
                    >
                      Send
                    </button>
                  </div>
                </div>
              </div>

              {/* Quick actions */}
              <div className="ops-panel p-4">
                <div className="ops-kicker mb-3">Quick actions</div>
                <div className="flex flex-wrap gap-2">
                  {QUICK_ACTIONS.map((qa) => (
                    <button
                      key={qa.label}
                      onClick={() => {
                        setInputValue(qa.query);
                        inputRef.current?.focus();
                      }}
                      disabled={sendMutation.isPending}
                      className="rounded-lg border border-white/10 bg-white/[.03] px-3 py-1.5 text-xs text-slate-300 transition hover:border-[#38d9c4]/40 hover:text-white disabled:opacity-40"
                    >
                      {qa.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Sidebar — compact approval queue */}
            <div className="space-y-4">
              <div className="ops-panel p-4">
                <div className="ops-kicker mb-1">Human approval gate</div>
                <div className="ops-title mb-3">Pending decisions</div>
                <p className="mb-4 text-xs leading-5 text-slate-400">
                  The AI cannot approve or execute these actions. Only a commander can.
                </p>
                {(queueData?.actions ?? []).slice(0, 3).map((action) => (
                  <CompactActionCard
                    key={action.action_id}
                    action={action}
                    onApprove={() => approveMutation.mutate({ id: action.action_id, status: "approved" })}
                    onReject={() =>  approveMutation.mutate({ id: action.action_id, status: "rejected" })}
                    loading={approveMutation.isPending}
                  />
                ))}
                {pendingCount === 0 && (
                  <p className="text-xs text-slate-500">No pending actions.</p>
                )}
                {pendingCount > 3 && (
                  <button
                    onClick={() => setActivePanel("approvals")}
                    className="mt-2 text-xs text-[#38d9c4] underline"
                  >
                    View all {pendingCount} →
                  </button>
                )}
              </div>

              <div className="ops-panel p-4">
                <div className="ops-kicker mb-2">Architecture note</div>
                <ul className="space-y-1.5 text-xs leading-5 text-slate-400">
                  <li>✓ Groq understands queries & calls tools</li>
                  <li>✓ Decision Engine produces priority scores</li>
                  <li>✓ XAI evidence shown for every score</li>
                  <li>✗ LLM cannot assign priority or dispatch</li>
                  <li>✗ LLM cannot approve actions</li>
                </ul>
              </div>
            </div>
          </div>
        )}

        {/* ── Evidence panel ───────────────────────────────────────────── */}
        {activePanel === "evidence" && (
          <EvidencePanel
            incidentId={selectedIncidentId}
            onSelectIncident={setSelectedIncidentId}
          />
        )}

        {/* ── Full approval queue ──────────────────────────────────────── */}
        {activePanel === "approvals" && (
          <ApprovalQueue
            actions={queueData?.actions ?? []}
            onApprove={(id) => approveMutation.mutate({ id, status: "approved" })}
            onReject={(id)  => approveMutation.mutate({ id, status: "rejected" })}
            loading={approveMutation.isPending}
            onRefresh={refetchQueue}
          />
        )}
      </div>
    </div>
  );
};

// ── Sub-components ────────────────────────────────────────────────────────

interface ChatBubbleProps {
  msg: ChatMessage;
  onSelectIncident: (id: string) => void;
}

const ChatBubble: React.FC<ChatBubbleProps> = ({ msg, onSelectIncident }) => {
  const isUser   = msg.role === "user";
  const isSystem = msg.role === "system";

  if (isSystem) {
    return (
      <div className="rounded-lg border border-[#38d9c4]/20 bg-[#38d9c4]/5 px-3 py-2 text-xs text-[#38d9c4]">
        {msg.content}
      </div>
    );
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-xl px-4 py-3 text-sm leading-6 ${
          isUser
            ? "bg-[#38d9c4]/20 text-white"
            : msg.isError
            ? "border border-[#ff6b6b]/30 bg-[#ff6b6b]/10 text-[#ff8b8b]"
            : "border border-white/10 bg-white/[.04] text-slate-200"
        }`}
      >
        {/* Message text */}
        <p className="whitespace-pre-wrap">{msg.content}</p>

        {/* Tool calls disclosure */}
        {msg.functionCalls && msg.functionCalls.length > 0 && (
          <details className="mt-2 text-xs text-slate-400">
            <summary className="cursor-pointer hover:text-slate-200">
              {msg.functionCalls.length} tool{msg.functionCalls.length !== 1 ? "s" : ""} invoked
            </summary>
            <div className="mt-1 space-y-1">
              {msg.functionCalls.map((fc, i) => (
                <div key={i} className="rounded bg-white/[.03] px-2 py-1 font-mono">
                  <span className="text-[#38d9c4]">{fc.name}</span>
                  {Object.keys(fc.arguments).length > 0 && (
                    <span className="ml-1 text-slate-500">
                      ({JSON.stringify(fc.arguments)})
                    </span>
                  )}
                  {/* If this tool returned an incident_id, offer to view evidence */}
                  {typeof fc.arguments.incident_id === "string" && (
                    <button
                      onClick={() => onSelectIncident(fc.arguments.incident_id as string)}
                      className="ml-2 text-[#38d9c4] underline"
                    >
                      View evidence
                    </button>
                  )}
                </div>
              ))}
            </div>
          </details>
        )}

        {/* Timestamp + model */}
        <div className="mt-1 flex gap-2 text-[10px] text-slate-500">
          <span>{msg.timestamp.toLocaleTimeString()}</span>
          {msg.modelUsed && <span>· {msg.modelUsed}</span>}
        </div>
      </div>
    </div>
  );
};


interface CompactActionCardProps {
  action:    Action;
  onApprove: () => void;
  onReject:  () => void;
  loading:   boolean;
}

const CompactActionCard: React.FC<CompactActionCardProps> = ({
  action,
  onApprove,
  onReject,
  loading,
}) => {
  const bandColour = PRIORITY_COLOURS[action.priority_band] ?? "text-slate-300";
  return (
    <div className="mb-3 rounded-lg border border-white/10 bg-white/[.03] p-3">
      <div className="mb-1 flex items-center justify-between">
        <span className={`ops-mono text-xs font-semibold ${bandColour}`}>
          {action.priority_band}
        </span>
        <span className="text-xs text-slate-500">{action.priority_score.toFixed(0)}/100</span>
      </div>
      <p className="mb-2 line-clamp-2 text-xs text-slate-300">
        {action.description?.slice(0, 100) || action.action_type}
      </p>
      <p className="mb-2 text-[10px] text-slate-500">
        Recommended by: {action.recommended_by}
      </p>
      <div className="flex gap-2">
        <button
          onClick={onApprove}
          disabled={loading}
          className="flex-1 rounded bg-[#38d9c4]/20 py-1 text-xs font-semibold text-[#38d9c4] transition hover:bg-[#38d9c4]/30 disabled:opacity-40"
        >
          Approve
        </button>
        <button
          onClick={onReject}
          disabled={loading}
          className="flex-1 rounded bg-[#ff6b6b]/20 py-1 text-xs font-semibold text-[#ff6b6b] transition hover:bg-[#ff6b6b]/30 disabled:opacity-40"
        >
          Reject
        </button>
      </div>
    </div>
  );
};
