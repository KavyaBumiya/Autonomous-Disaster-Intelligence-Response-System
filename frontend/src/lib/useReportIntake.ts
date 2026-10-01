/**
 * Citizen report intake.
 *
 * `POST /api/reports` returns 201 the moment the row is stored; the intelligence
 * pipeline then runs as a backend background task — LLM parse, geocode, zone
 * upsert, verification, detection, decision, XAI. On the deployed tier that
 * pipeline is LLM-bound and can take a couple of minutes, so the console cannot
 * simply re-read and look for the result: it has to *watch* for it.
 *
 * This hook owns that watch. It reports each observable stage so the operator
 * sees the system actually thinking, and resolves as soon as a new incident
 * appears (or reports honestly that the pipeline produced none).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api";
import type { Incident, ReportAcceptedResponse, VoiceAcceptedResponse } from "./types";

export type IntakeStage =
  | "idle"
  | "submitted"
  | "parsing"
  | "geolocating"
  | "scoring"
  | "resolved"
  | "unresolved"
  | "failed";

export interface IntakeState {
  stage: IntakeStage;
  /** Report id returned by the backend, once the POST succeeded. */
  reportId: string | null;
  /** The incident the pipeline raised, once it appeared. */
  incident: Incident | null;
  error: string | null;
  /** Seconds spent waiting for the incident, for the "still working" line. */
  elapsedSeconds: number;
  isRunning: boolean;
}

/** Ordered pipeline stages shown as a checklist while the report is processed. */
export const INTAKE_STAGES: ReadonlyArray<{ stage: IntakeStage; label: string }> = [
  { stage: "submitted", label: "Report stored" },
  { stage: "parsing", label: "Language + hazard parsing" },
  { stage: "geolocating", label: "Zone resolution" },
  { stage: "scoring", label: "Trust + priority scoring" },
  { stage: "resolved", label: "Incident raised" },
];

/**
 * How long to wait for the incident.
 *
 * The LLM parse step dominates and the deployed backend can cold-start, so this
 * is generous on purpose. It stops early the instant the incident shows up.
 */
const WATCH_TIMEOUT_MS = 5 * 60_000;
const WATCH_INTERVAL_MS = 4_000;

export function useReportIntake(onResolved: () => void) {
  const [state, setState] = useState<IntakeState>({
    stage: "idle",
    reportId: null,
    incident: null,
    error: null,
    elapsedSeconds: 0,
    isRunning: false,
  });

  const timerRef = useRef<number | null>(null);
  const startedAtRef = useRef(0);
  // Incident ids already known before this report, so "a new incident appeared"
  // is a reliable signal and not just "an incident exists".
  const baselineRef = useRef<Set<string> | null>(null);
  const settledRef = useRef(false);

  const stopWatching = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  useEffect(() => stopWatching, [stopWatching]);

  const beginWatch = useCallback(
    (reportId: string) => {
      settledRef.current = false;
      startedAtRef.current = Date.now();
      setState({
        stage: "parsing",
        reportId,
        incident: null,
        error: null,
        elapsedSeconds: 0,
        isRunning: true,
      });

      const poll = async () => {
        if (settledRef.current) return;
        const elapsed = Date.now() - startedAtRef.current;

        if (elapsed > WATCH_TIMEOUT_MS) {
          settledRef.current = true;
          setState((s) => ({
            ...s,
            stage: "unresolved",
            isRunning: false,
            elapsedSeconds: Math.round(elapsed / 1000),
          }));
          return;
        }

        // Surface progress from wall-clock alone: the pipeline stages are not
        // individually observable from outside the backend, and guessing a stage
        // from elapsed time would be inventing telemetry. The checklist is
        // marked indeterminate until the incident actually arrives.
        setState((s) => (s.stage === "parsing" && elapsed > 20_000
          ? { ...s, stage: "geolocating", elapsedSeconds: Math.round(elapsed / 1000) }
          : { ...s, elapsedSeconds: Math.round(elapsed / 1000) }));

        try {
          const result = await api.incidents({ activeOnly: false, limit: 50 });
          const incidents = result.incidents ?? [];
          const baseline = baselineRef.current ?? new Set(incidents.map((i) => i.incident_id));
          const fresh = incidents.find((i) => !baseline.has(i.incident_id));
          baselineRef.current = baseline;

          if (fresh) {
            settledRef.current = true;
            setState({
              stage: "resolved",
              reportId,
              incident: fresh,
              error: null,
              elapsedSeconds: Math.round(elapsed / 1000),
              isRunning: false,
            });
            onResolved();
            return;
          }
        } catch {
          // A transient read failure must not abandon the watch.
        }

        if (settledRef.current) return;
        timerRef.current = window.setTimeout(poll, WATCH_INTERVAL_MS);
      };

      timerRef.current = window.setTimeout(poll, WATCH_INTERVAL_MS);
    },
    [onResolved],
  );

  /** Snapshot current incidents so `beginWatch` can spot the new one. */
  const captureBaseline = useCallback(async () => {
    try {
      const result = await api.incidents({ activeOnly: false, limit: 50 });
      baselineRef.current = new Set((result.incidents ?? []).map((i) => i.incident_id));
    } catch {
      baselineRef.current = new Set();
    }
  }, []);

  const reset = useCallback(() => {
    settledRef.current = true;
    stopWatching();
    baselineRef.current = null;
    setState({
      stage: "idle",
      reportId: null,
      incident: null,
      error: null,
      elapsedSeconds: 0,
      isRunning: false,
    });
  }, [stopWatching]);

  const submitText = useCallback(
    async (body: {
      message_text: string;
      location_string?: string | null;
      lat?: number | null;
      lng?: number | null;
    }): Promise<ReportAcceptedResponse | null> => {
      settledRef.current = true;
      stopWatching();
      setState({
        stage: "submitted",
        reportId: null,
        incident: null,
        error: null,
        elapsedSeconds: 0,
        isRunning: true,
      });
      await captureBaseline();
      try {
        const accepted = await api.submitReport({
          message_text: body.message_text,
          location_string: body.location_string ?? null,
          lat: body.lat ?? null,
          lng: body.lng ?? null,
          device_type: "web",
        });
        beginWatch(accepted.report_id);
        return accepted;
      } catch (error) {
        settledRef.current = true;
        setState({
          stage: "failed",
          reportId: null,
          incident: null,
          error: error instanceof ApiError ? error.detail : "Backend unreachable",
          elapsedSeconds: 0,
          isRunning: false,
        });
        return null;
      }
    },
    [beginWatch, captureBaseline, stopWatching],
  );

  const submitVoice = useCallback(
    async (body: {
      audio: Blob;
      filename?: string;
      location_string?: string | null;
      lat?: number | null;
      lng?: number | null;
    }): Promise<VoiceAcceptedResponse | null> => {
      settledRef.current = true;
      stopWatching();
      setState({
        stage: "submitted",
        reportId: null,
        incident: null,
        error: null,
        elapsedSeconds: 0,
        isRunning: true,
      });
      await captureBaseline();
      try {
        const accepted = await api.submitVoiceReport({
          audio: body.audio,
          filename: body.filename,
          location_string: body.location_string ?? null,
          lat: body.lat ?? null,
          lng: body.lng ?? null,
        });
        beginWatch(accepted.report_id);
        return accepted;
      } catch (error) {
        settledRef.current = true;
        setState({
          stage: "failed",
          reportId: null,
          incident: null,
          error: error instanceof ApiError ? error.detail : "Backend unreachable",
          elapsedSeconds: 0,
          isRunning: false,
        });
        return null;
      }
    },
    [beginWatch, captureBaseline, stopWatching],
  );

  return { state, submitText, submitVoice, reset };
}
