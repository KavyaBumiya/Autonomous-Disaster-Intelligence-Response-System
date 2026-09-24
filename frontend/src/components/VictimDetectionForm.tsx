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
    <div className="card p-6 max-w-md mx-auto">
      <h2 className="text-2xl font-bold mb-4">Victim Detection</h2>

      {/* File upload */}
      <div className="mb-4">
        <label className="cursor-pointer bg-blue-500 text-white font-medium rounded-lg
          px-4 py-2 inline-block text-center">
          <input
            ref={imageRef}
            type="file"
            accept="image/*"
            onChange={handleFileChange}
            className="hidden"
          />
          {imageFile ? (
            <span>Change image</span>
          ) : (
            <span>Upload image for victim detection</span>
          )}
        </label>
      </div>

      {/* Detection button */}
      {loading ? (
        <p className="text-yellow-300">Analyzing image...</p>
      ) : (
        <button
          onClick={detectVictims}
          disabled={!imageFile}
          className="mt-4 bg-green-600 text-white font-medium rounded-lg px-4 py-2 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Detect Victims
        </button>
      )}

      {/* Results */}
      {showResult && (
        <div className="mt-6 p-4 bg-gray-800/50 rounded-lg">
          <p className="font-medium text-white mb-2">
            Detection Results:
          </p>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-gray-400">Victims found:</span>
              <span className="font-bold text-white">{victimCount}</span>
            </div>
            <div>
              <span className="text-gray-400">Confidence:</span>
              <span className="font-bold text-yellow-400">
                {confidence.toFixed(2)}
              </span>
            </div>
          </div>

          {locations.length > 0 && (
            <div className="mt-3">
              <span className="text-gray-400 block text-xs">Location data:</span>
              {locations.map((loc, i) => (
                <div key={i} className="text-xs text-gray-300">
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