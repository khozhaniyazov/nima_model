"use client";

import { useState } from "react";
import { TopExample } from "@/lib/api";

const API_BASE = "http://localhost:5000";

interface TopExamplesProps {
  examples: TopExample[];
}

function getScoreColor(score: number): string {
  if (score >= 80) return "var(--accent-green)";
  if (score >= 60) return "var(--accent-yellow)";
  return "var(--accent-magenta)";
}

function getScoreTier(score: number): string {
  if (score >= 80) return "EXCELLENT";
  if (score >= 70) return "GOOD";
  if (score >= 60) return "FAIR";
  return "NEEDS_WORK";
}

export default function TopExamples({ examples }: TopExamplesProps) {
  const [selectedExample, setSelectedExample] = useState<TopExample | null>(null);

  if (examples.length === 0) {
    return (
      <section>
        <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", marginBottom: 8, letterSpacing: "0.2em" }}>
          {"/// TOP_EXAMPLES"}
        </div>
        <div className="border-box" style={{ padding: "40px", textAlign: "center" }}>
          <div style={{ color: "var(--text-muted)", fontSize: "0.85rem", letterSpacing: "0.1em" }}>
            NO_EXAMPLES_FOUND
          </div>
          <div style={{ color: "var(--text-muted)", fontSize: "0.7rem", marginTop: "8px", letterSpacing: "0.05em" }}>
            High-scoring examples will appear here after renders achieve quality scores ≥80
          </div>
        </div>
      </section>
    );
  }

  return (
    <section>
      <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", marginBottom: 8, letterSpacing: "0.2em" }}>
        {"/// TOP_EXAMPLES"}
      </div>
      
      {selectedExample && (
        <div
          className="border-box animate-fade-in-up"
          style={{ padding: "20px", marginBottom: "16px", border: "1px solid var(--accent-cyan)" }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "16px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
              <span
                style={{
                  padding: "4px 12px",
                  border: "1px solid var(--accent-cyan)",
                  fontSize: "0.7rem",
                  letterSpacing: "0.1em",
                  color: "var(--accent-cyan)",
                }}
              >
                {selectedExample.domain.toUpperCase()}
              </span>
              <span style={{ fontSize: "0.85rem", color: "var(--text-primary)" }}>
                SCORE: {selectedExample.overall_score.toFixed(0)}
              </span>
            </div>
            <button
              onClick={() => setSelectedExample(null)}
              style={{
                background: "none",
                border: "1px solid var(--border-strong)",
                color: "var(--text-muted)",
                padding: "4px 12px",
                fontSize: "0.75rem",
                cursor: "pointer",
              }}
            >
              [ CLOSE ]
            </button>
          </div>

          <div style={{ fontSize: "0.85rem", color: "var(--text-secondary)", marginBottom: "16px", lineHeight: 1.6 }}>
            {selectedExample.prompt}
          </div>

          {selectedExample.video_path && (
            <div className="video-frame">
              <video
                controls
                autoPlay
                loop
                src={`${API_BASE}/outputs/${selectedExample.video_path}`}
                style={{ width: "100%", height: "auto", display: "block" }}
              />
            </div>
          )}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: "16px" }}>
        {examples.map((example, i) => (
          <div
            key={i}
            className="border-box"
            style={{ padding: "16px", cursor: "pointer", transition: "border-color 0.2s" }}
            onClick={() => setSelectedExample(example)}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "12px" }}>
              <span
                style={{
                  padding: "2px 8px",
                  border: "1px solid var(--accent-cyan)",
                  fontSize: "0.65rem",
                  letterSpacing: "0.1em",
                  color: "var(--accent-cyan)",
                }}
              >
                {example.domain.toUpperCase()}
              </span>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: "1.4rem", fontWeight: 700, color: getScoreColor(example.overall_score) }}>
                  {example.overall_score.toFixed(0)}
                </div>
                <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", letterSpacing: "0.05em" }}>
                  {getScoreTier(example.overall_score)}
                </div>
              </div>
            </div>

            <div
              style={{
                fontSize: "0.8rem",
                color: "var(--text-secondary)",
                marginBottom: "12px",
                overflow: "hidden",
                textOverflow: "ellipsis",
                display: "-webkit-box",
                WebkitLineClamp: 2,
                WebkitBoxOrient: "vertical",
                lineHeight: 1.4,
              }}
            >
              {example.prompt}
            </div>

            <div style={{ display: "flex", gap: "12px", fontSize: "0.65rem", color: "var(--text-muted)" }}>
              <span>V:{example.visual_quality_score.toFixed(0)}</span>
              <span>E:{example.educational_value_score.toFixed(0)}</span>
              <span>P:{example.pacing.toFixed(0)}</span>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
