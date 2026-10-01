import { useRef, useState } from "react";
import * as Icons from "lucide-react";
import { useConsoleData } from "../lib/consoleData";
import { PageHeader, PanelTitle, MiniStat } from "../components/ui";
import { INTAKE_STAGES, useReportIntake, type IntakeStage } from "../lib/useReportIntake";

const { Mic, Send, ShieldCheck, Loader2, CheckCircle2, AlertTriangle, X, MapPin, Radio } = Icons;

/** Ordered stage -> label lookup for the checklist. */
const STAGE_ORDER: IntakeStage[] = ["submitted", "parsing", "geolocating", "scoring", "resolved"];

const SAMPLE = "Water is rising fast near the Sabarmati river belt. Two families are stranded on a rooftop and we cannot get to them.";

export function ReportIntake({ notify, setActiveNav }: any) {
  const { zone, refreshAll } = useConsoleData();
  const { state, submitText, submitVoice, reset } = useReportIntake(refreshAll);

  const [text, setText] = useState("");
  const [place, setPlace] = useState("");
  const [recording, setRecording] = useState(false);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  const busy = state.isRunning;

  const submit = async () => {
    if (!text.trim() || busy) return;
    // Default to the monitored zone's centroid so the report is spatially
    // actionable. Without coordinates the pipeline skips the whole spatial
    // chain, which is correct behaviour but makes for a confusing demo.
    const accepted = await submitText({
      message_text: text.trim(),
      location_string: place.trim() || zone?.name || null,
      lat: zone?.centroid_lat ?? null,
      lng: zone?.centroid_lng ?? null,
    });
    if (accepted) {
      setText("");
      notify("Report accepted — AegisAI pipeline running");
    } else {
      notify(`Report rejected: ${state.error ?? "backend unavailable"}`);
    }
  };

  const toggleRecording = async () => {
    if (recording) {
      mediaRef.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        setRecording(false);
        const audio = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        if (audio.size < 1024) return notify("Recording too short to transcribe");
        const accepted = await submitVoice({
          audio,
          filename: "field-report.webm",
          location_string: place.trim() || zone?.name || null,
          lat: zone?.centroid_lat ?? null,
          lng: zone?.centroid_lng ?? null,
        });
        if (accepted) notify("Voice report received — transcription and pipeline running");
      };
      recorder.start();
      mediaRef.current = recorder;
      setRecording(true);
    } catch {
      notify("Microphone permission denied");
    }
  };

  const stageIndex = state.stage === "unresolved" || state.stage === "failed"
    ? -1
    : STAGE_ORDER.indexOf(state.stage);

  return (
    <>
      <PageHeader
        eyebrow="Intake / Citizen reports"
        title="Report intake"
        description="Submit a field or citizen report and watch AegisAI parse it, geolocate it, verify its trust and raise a scored incident."
      >
        <span className="chip">
          <ShieldCheck size={12} className="text-cyan" /> Human report → deterministic scoring
        </span>
      </PageHeader>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <section className="panel p-4">
          <PanelTitle eyebrow="New signal" title="Describe what is happening" />
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={busy}
            placeholder={SAMPLE}
            className="mt-4 min-h-40 w-full rounded-xl border border-line bg-slate-950/50 p-3 text-xs leading-5 text-white outline-none placeholder:text-slate-600 focus:border-cyan/40 disabled:opacity-60"
          />
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <label className="text-[11px] text-slate-400">
              Location
              <div className="relative mt-1">
                <MapPin size={13} className="absolute left-3 top-3 text-slate-600" />
                <input
                  value={place}
                  onChange={(e) => setPlace(e.target.value)}
                  disabled={busy}
                  placeholder={zone?.name ?? "e.g. Alkapuri, Vadodara"}
                  className="h-10 w-full rounded-lg border border-line bg-slate-950/50 pl-9 pr-3 text-xs text-white outline-none placeholder:text-slate-600 disabled:opacity-60"
                />
              </div>
            </label>
            <div className="flex items-end gap-2">
              <button
                onClick={submit}
                disabled={busy || !text.trim()}
                className="flex h-10 flex-1 items-center justify-center gap-2 rounded-lg bg-cyan text-xs font-bold text-[#04101b] disabled:opacity-50"
              >
                {busy ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
                Submit report
              </button>
              <button
                onClick={toggleRecording}
                disabled={busy}
                title={recording ? "Stop recording" : "Record a voice report"}
                className={`flex h-10 w-10 items-center justify-center rounded-lg border transition disabled:opacity-50 ${
                  recording ? "border-danger/40 bg-danger/10 text-danger" : "border-line text-slate-400 hover:text-white"
                }`}
              >
                <Mic size={15} />
              </button>
            </div>
          </div>
          <p className="mt-3 text-[10px] leading-5 text-slate-500">
            Coordinates default to the monitored zone centroid so the spatial pipeline engages. A report
            without any location is stored and audited, but never raises an incident — the console will
            not place a hazard it cannot locate.
          </p>
        </section>

        <section className="space-y-4">
          <div className="panel p-4">
            <div className="flex items-center justify-between">
              <PanelTitle eyebrow="Pipeline" title="Processing status" />
              {state.isRunning && (
                <span className="flex items-center gap-1.5 text-[10px] text-cyan">
                  <Radio size={11} className="animate-pulse" /> {state.elapsedSeconds}s
                </span>
              )}
            </div>

            {state.stage === "idle" && (
              <p className="mt-4 rounded-xl border border-line bg-slate-950/30 p-3 text-[11px] leading-5 text-slate-500">
                No report submitted in this session. Submit one to see the full intelligence chain run
                end to end.
              </p>
            )}

            {state.stage !== "idle" && (
              <div className="mt-4 space-y-2">
                {INTAKE_STAGES.map((step, index) => {
                  const done = stageIndex >= 0 && index < stageIndex;
                  const current = index === stageIndex;
                  return (
                    <div key={step.stage} className="flex items-center gap-2.5">
                      <div
                        className={`flex h-5 w-5 items-center justify-center rounded-full text-[9px] font-bold ${
                          done
                            ? "bg-success/15 text-success"
                            : current
                              ? "bg-cyan/15 text-cyan"
                              : "bg-slate-800 text-slate-600"
                        }`}
                      >
                        {done ? <CheckCircle2 size={12} /> : current ? <Loader2 size={11} className="animate-spin" /> : index + 1}
                      </div>
                      <span
                        className={`text-[11px] ${
                          done ? "text-slate-400" : current ? "font-semibold text-cyan" : "text-slate-600"
                        }`}
                      >
                        {step.label}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}

            {state.reportId && (
              <p className="mt-3 truncate font-mono text-[9px] text-slate-600">report {state.reportId}</p>
            )}

            {state.stage === "unresolved" && (
              <div className="mt-4 rounded-xl border border-amber/20 bg-amber/[.04] p-3">
                <p className="text-[10px] font-semibold text-amber">No incident after 5 minutes</p>
                <p className="mt-1 text-[11px] leading-5 text-slate-400">
                  The report was accepted, but the pipeline did not surface an incident within the watch
                  window. That is a real backend outcome, not a UI failure — check the report list.
                </p>
              </div>
            )}

            {state.stage === "failed" && (
              <div className="mt-4 rounded-xl border border-danger/25 bg-danger/[.04] p-3">
                <p className="text-[10px] font-semibold text-danger">Submission failed</p>
                <p className="mt-1 text-[11px] leading-5 text-slate-400">{state.error}</p>
              </div>
            )}

            {state.incident && (
              <div className="mt-4 rounded-xl border border-success/25 bg-success/[.04] p-3">
                <p className="text-[10px] font-semibold text-success">Incident raised</p>
                <p className="mt-1 text-[11px] leading-5 text-slate-300">
                  {state.incident.disaster_type ?? "Unclassified"} · priority{" "}
                  {Math.round(state.incident.priority_score)}/100 · confidence{" "}
                  {Math.round((state.incident.confidence ?? 0) * 100)}%
                </p>
                <button
                  onClick={() => setActiveNav("Incidents")}
                  className="mt-3 w-full rounded-lg bg-cyan py-2 text-[11px] font-bold text-[#04101b]"
                >
                  Open in incident queue
                </button>
              </div>
            )}

            {state.stage !== "idle" && state.stage !== "resolved" && (
              <button
                onClick={reset}
                className="mt-4 flex w-full items-center justify-center gap-2 rounded-lg border border-line py-2 text-[11px] font-semibold text-slate-300"
              >
                <X size={12} /> Clear
              </button>
            )}
          </div>

          {zone && (
            <div className="panel p-4">
              <p className="eyebrow">Geocoding target</p>
              <div className="mt-3 grid grid-cols-2 gap-2">
                <MiniStat label="Zone" value={zone.name} />
                <MiniStat label="Radius" value={`${Math.round(zone.radius_meters)} m`} />
                <MiniStat label="Lat" value={zone.centroid_lat.toFixed(4)} />
                <MiniStat label="Lng" value={zone.centroid_lng.toFixed(4)} />
              </div>
              <p className="mt-3 flex gap-2 text-[10px] leading-5 text-slate-500">
                <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber" />
                Reports inside this radius merge into one incident. Corroboration from neighbouring
                zones is folded in by the clustering agent.
              </p>
            </div>
          )}
        </section>
      </div>
    </>
  );
}
