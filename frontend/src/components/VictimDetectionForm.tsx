import React, { useState, useRef } from "react";
import { toast } from "sonner";
import { default as api, apiErrorMessage } from "@/services/api";

interface VictimDetectionFormProps {
  incidentId: string;
  reportIds: string[];
}

export const VictimDetectionForm: React.FC<VictimDetectionFormProps> = ({
  reportIds,
}) => {
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [victimCount, setVictimCount] = useState(0);
  const [confidence, setConfidence] = useState(0);
  const [locations, setLocations] = useState<number[][]>([]);
  const [loading, setLoading] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const imageRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setImageFile(file);
      setVictimCount(0);
      setConfidence(0);
      setLocations([]);
      setShowResult(false);
    }
  };

  const detectVictims = async () => {
    if (!imageFile) {
      toast.error("Please select an image first");
      return;
    }
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("image", imageFile);

      const res = await api.post(
        `/api/reports/${reportIds[0]}/victim-detect`,
        formData,
        {
          headers: {
            "Content-Type": "multipart/form-data",
          },
        }
      );

      setVictimCount(res.data.victim_count);
      setConfidence(res.data.confidence_score);
      setLocations(res.data.victim_locations || []);
      setShowResult(true);
    } catch (err) {
      toast.error(apiErrorMessage(err) || "Victim detection failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="ops-panel p-6 max-w-md mx-auto">
      <div className="ops-kicker mb-2">Vision</div>
      <h2 className="ops-title mb-4">Victim detection</h2>

      {/* File upload */}
      <div className="mb-4">
        <label className="ops-button cursor-pointer text-center">
          <input
            ref={imageRef}
            type="file"
            accept="image/*"
            onChange={handleFileChange}
            className="hidden"
          />
          {imageFile ? <span>Change image</span> : <span>Upload image for victim detection</span>}
        </label>
      </div>

      {/* Detection button */}
      {loading ? (
        <p className="ops-mono text-sm text-[#f3b562]">Analyzing image…</p>
      ) : (
        <button
          type="button"
          onClick={detectVictims}
          disabled={!imageFile}
          className="ops-button ops-button-primary"
        >
          Detect victims
        </button>
      )}

      {/* Results */}
      {showResult && (
        <div className="ops-panel-flat mt-6 p-4">
          <p className="ops-kicker mb-2">Detection results</p>
          <div className="ops-kpi-grid" style={{ gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            <div>
              <span className="ops-stat-label">Victims found</span>
              <div className="text-lg font-bold text-white">{victimCount}</div>
            </div>
            <div>
              <span className="ops-stat-label">Confidence</span>
              <div className="text-lg font-bold text-[#f3b562]">{confidence.toFixed(2)}</div>
            </div>
          </div>

          {locations.length > 0 && (
            <div className="mt-3">
              <span className="ops-stat-label block">Location data</span>
              {locations.map((loc, i) => (
                <div key={i} className="ops-mono text-xs text-slate-300">
                  bbox: {JSON.stringify(loc)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};