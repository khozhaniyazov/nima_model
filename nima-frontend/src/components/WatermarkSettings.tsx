"use client";

import { useState, useEffect } from "react";

export interface WatermarkConfig {
  enabled: boolean;
  text: string;
  position: "top-left" | "top-right" | "bottom-left" | "bottom-right";
  opacity: number;
}

export interface IntroOutroConfig {
  enabled: boolean;
  introText: string;
  outroText: string;
}

interface WatermarkSettingsProps {
  watermark: WatermarkConfig;
  setWatermark: (w: WatermarkConfig) => void;
  introOutro: IntroOutroConfig;
  setIntroOutro: (i: IntroOutroConfig) => void;
}

const POSITIONS = [
  { value: "top-left", label: "Top Left" },
  { value: "top-right", label: "Top Right" },
  { value: "bottom-left", label: "Bottom Left" },
  { value: "bottom-right", label: "Bottom Right" },
] as const;

export default function WatermarkSettings({
  watermark,
  setWatermark,
  introOutro,
  setIntroOutro,
}: WatermarkSettingsProps) {
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("nima-watermark");
    if (saved) {
      try {
        setWatermark(JSON.parse(saved));
      } catch {}
    }
    const savedIO = localStorage.getItem("nima-intro-outro");
    if (savedIO) {
      try {
        setIntroOutro(JSON.parse(savedIO));
      } catch {}
    }
  }, [setIntroOutro, setWatermark]);

  const handleSave = () => {
    localStorage.setItem("nima-watermark", JSON.stringify(watermark));
    localStorage.setItem("nima-intro-outro", JSON.stringify(introOutro));
  };

  const updateWatermark = (updates: Partial<WatermarkConfig>) => {
    const next = { ...watermark, ...updates };
    setWatermark(next);
    localStorage.setItem("nima-watermark", JSON.stringify(next));
  };

  const updateIntroOutro = (updates: Partial<IntroOutroConfig>) => {
    const next = { ...introOutro, ...updates };
    setIntroOutro(next);
    localStorage.setItem("nima-intro-outro", JSON.stringify(next));
  };

  return (
    <div style={{ marginTop: 16 }}>
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          background: "none",
          border: "1px solid var(--border-strong)",
          color: "var(--text-secondary)",
          padding: "8px 16px",
          cursor: "pointer",
          fontSize: "0.75rem",
          letterSpacing: "0.1em",
          width: "100%",
          textAlign: "left" as const,
        }}
      >
        {expanded ? "▼" : "▶"} BRANDING_OPTIONS
      </button>

      {expanded && (
        <div
          style={{
            border: "1px solid var(--border-strong)",
            borderTop: "none",
            padding: 16,
            background: "var(--bg-panel)",
          }}
        >
          <div style={{ marginBottom: 16 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 8,
              }}
            >
              <input
                type="checkbox"
                id="watermark-enabled"
                checked={watermark.enabled}
                onChange={(e) => updateWatermark({ enabled: e.target.checked })}
                style={{ width: "auto" }}
              />
              <label
                htmlFor="watermark-enabled"
                style={{ fontSize: "0.75rem", cursor: "pointer" }}
              >
                WATERMARK
              </label>
            </div>

            {watermark.enabled && (
              <div style={{ paddingLeft: 24 }}>
                <div style={{ marginBottom: 8 }}>
                  <label
                    style={{ fontSize: "0.65rem", display: "block", marginBottom: 4 }}
                  >
                    TEXT
                  </label>
                  <input
                    type="text"
                    value={watermark.text}
                    onChange={(e) => updateWatermark({ text: e.target.value })}
                    placeholder="NIMA"
                    style={{
                      width: "100%",
                      padding: "6px 8px",
                      background: "var(--bg-input)",
                      border: "1px solid var(--border-strong)",
                      color: "var(--text-primary)",
                      fontSize: "0.75rem",
                    }}
                  />
                </div>

                <div style={{ marginBottom: 8 }}>
                  <label
                    style={{ fontSize: "0.65rem", display: "block", marginBottom: 4 }}
                  >
                    POSITION
                  </label>
                  <select
                    value={watermark.position}
                    onChange={(e) =>
                      updateWatermark({
                        position: e.target.value as WatermarkConfig["position"],
                      })
                    }
                    style={{
                      width: "100%",
                      padding: "6px 8px",
                      background: "var(--bg-input)",
                      border: "1px solid var(--border-strong)",
                      color: "var(--text-primary)",
                      fontSize: "0.75rem",
                    }}
                  >
                    {POSITIONS.map((p) => (
                      <option key={p.value} value={p.value}>
                        {p.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label
                    style={{ fontSize: "0.65rem", display: "block", marginBottom: 4 }}
                  >
                    OPACITY: {watermark.opacity}%
                  </label>
                  <input
                    type="range"
                    min="10"
                    max="100"
                    step="10"
                    value={watermark.opacity}
                    onChange={(e) =>
                      updateWatermark({ opacity: Number(e.target.value) })
                    }
                    style={{ width: "100%" }}
                  />
                </div>
              </div>
            )}
          </div>

          <div style={{ marginBottom: 8 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                marginBottom: 8,
              }}
            >
              <input
                type="checkbox"
                id="io-enabled"
                checked={introOutro.enabled}
                onChange={(e) => updateIntroOutro({ enabled: e.target.checked })}
                style={{ width: "auto" }}
              />
              <label
                htmlFor="io-enabled"
                style={{ fontSize: "0.75rem", cursor: "pointer" }}
              >
                INTRO/OUTRO
              </label>
            </div>

            {introOutro.enabled && (
              <div style={{ paddingLeft: 24 }}>
                <div style={{ marginBottom: 8 }}>
                  <label
                    style={{ fontSize: "0.65rem", display: "block", marginBottom: 4 }}
                  >
                    INTRO TEXT
                  </label>
                  <input
                    type="text"
                    value={introOutro.introText}
                    onChange={(e) =>
                      updateIntroOutro({ introText: e.target.value })
                    }
                    placeholder="Welcome to this animation"
                    style={{
                      width: "100%",
                      padding: "6px 8px",
                      background: "var(--bg-input)",
                      border: "1px solid var(--border-strong)",
                      color: "var(--text-primary)",
                      fontSize: "0.75rem",
                    }}
                  />
                </div>
                <div>
                  <label
                    style={{ fontSize: "0.65rem", display: "block", marginBottom: 4 }}
                  >
                    OUTRO TEXT
                  </label>
                  <input
                    type="text"
                    value={introOutro.outroText}
                    onChange={(e) =>
                      updateIntroOutro({ outroText: e.target.value })
                    }
                    placeholder="Thank you for watching"
                    style={{
                      width: "100%",
                      padding: "6px 8px",
                      background: "var(--bg-input)",
                      border: "1px solid var(--border-strong)",
                      color: "var(--text-primary)",
                      fontSize: "0.75rem",
                    }}
                  />
                </div>
              </div>
            )}
          </div>

          <button
            onClick={handleSave}
            style={{
              background: "var(--accent-cyan)",
              border: "none",
              color: "#000",
              padding: "8px 16px",
              cursor: "pointer",
              fontSize: "0.75rem",
              fontWeight: 600,
            }}
          >
            SAVE_SETTINGS
          </button>
        </div>
      )}
    </div>
  );
}
