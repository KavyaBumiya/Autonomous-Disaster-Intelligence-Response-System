import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { useAssistant } from "../lib/useAssistant";
import { PageHeader, PanelTitle } from "../components/ui";

const { Radio, Send, CheckCircle2 } = Icons;

export type Role = "Command" | "Rescue" | "NGO";

const INITIAL_ASSISTANT_MESSAGES: { who: "user" | "ai"; text: string }[] = [];

const IOT_PROMPTS = [
  "What's the current water level?",
  "Show IoT sensor status",
  "Is the flood risk critical?",
  "Get flow velocity reading",
];

const ALL_PROMPTS = [
  "Summarize the current situation",
  "Which team should move next?",
  "Show blocked routes",
  "What resources are low?",
  "Explain the flood prediction",
  ...IOT_PROMPTS,
];

export function AssistantPage({ role, notify }: { role: Role; notify: (s: string) => void }) {
  const { zoneId, feedHealth, topIncident, zoneName } = useConsoleData();
  const assistant = useAssistant(INITIAL_ASSISTANT_MESSAGES, zoneId, notify);
  const { messages, input, setInput, send } = assistant;
  const contextLabel = topIncident?.incident_id ?? "No active incident";

  return (
    <>
      <PageHeader
        eyebrow="AI systems / Assistant"
        title="Ask AegisAI"
        description="Conversational access to the live operational picture, with traceable recommendations and explicit operator confirmation."
      >
        <span className="chip">
          <Radio size={12} className={assistant.lastReplyFromAi ? "text-success" : "text-slate-500"} />
          {" "}Live context · {role} mode
        </span>
      </PageHeader>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <section className="panel flex min-h-[620px] flex-col">
          <div className="border-b border-line px-4 py-3">
            <p className="text-xs font-semibold">Operational conversation</p>
            <p className="mt-1 text-[10px] text-slate-500">
              Context: {contextLabel} · {zoneName} · {feedHealth.sourceCount} connected sources
            </p>
          </div>
          <div className="flex-1 space-y-4 overflow-auto p-4">
            {messages.map((m, i) => (
              <div key={i} className={`flex ${m.who === "user" ? "justify-end" : ""}`}>
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-3 text-xs leading-5 ${
                    m.who === "user"
                      ? "bg-cyan text-[#04101b]"
                      : "border border-line bg-slate-950/40 text-slate-300"
                  }`}
                >
                  {m.text}
                </div>
              </div>
            ))}
            {assistant.isThinking && (
              <div className="flex">
                <div className="rounded-2xl border border-line bg-slate-950/40 px-4 py-3 text-xs text-slate-500">
                  Correlating live context...
                </div>
              </div>
            )}
          </div>
          <div className="border-t border-line p-3">
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && send()}
                placeholder="Ask about incidents, IoT sensors, routes, resources..."
                className="h-11 min-w-0 flex-1 rounded-xl border border-line bg-slate-950/50 px-3 text-xs outline-none focus:border-cyan/40"
              />
              <button
                onClick={send}
                className="flex h-11 w-11 items-center justify-center rounded-xl bg-cyan text-[#04101b]"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
        </section>
        <section className="space-y-4">
          <div className="panel p-4">
            <PanelTitle eyebrow="Suggested prompts" title="Quick actions" />
            <div className="mt-3 space-y-2">
              {ALL_PROMPTS.map((p) => (
                <button
                  key={p}
                  onClick={() => {
                    setInput(p);
                    send();
                  }}
                  className="w-full rounded-lg border border-line bg-slate-950/30 px-3 py-2 text-left text-[11px] text-slate-300 transition hover:border-cyan/40 hover:text-white"
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
          <div className="panel p-4">
            <PanelTitle eyebrow="AI Core" title="MVP Capabilities" />
            <div className="mt-3 space-y-2 text-[11px] text-slate-400">
              <p><span className="text-cyan">Incident Analysis</span> — priority, XAI evidence, victim estimates</p>
              <p><span className="text-cyan">IoT Telemetry</span> — water level, flow velocity, device health</p>
              <p><span className="text-cyan">Resource Command</span> — availability, allocation, dispatch</p>
              <p><span className="text-cyan">Route Intelligence</span> — disaster-aware routing, blockages</p>
              <p><span className="text-cyan">Predictions</span> — flood/fire spread modeling</p>
            </div>
          </div>
          <div className="panel p-4">
            <PanelTitle eyebrow="Trust layer" title="Every answer should show" />
            <div className="mt-3 space-y-3 text-[11px] text-slate-400">
              <div className="flex gap-2"><CheckCircle2 size={14} className="text-success" /> Evidence sources</div>
              <div className="flex gap-2"><CheckCircle2 size={14} className="text-success" /> Confidence / uncertainty</div>
              <div className="flex gap-2"><CheckCircle2 size={14} className="text-success" /> Recommended action</div>
              <div className="flex gap-2"><CheckCircle2 size={14} className="text-success" /> Human confirmation required</div>
            </div>
          </div>
        </section>
      </div>
    </>
  );
}
