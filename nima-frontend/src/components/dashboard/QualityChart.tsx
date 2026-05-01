"use client";

import { StatsResponse } from "@/lib/api";

interface QualityChartProps {
  qualityTiers: StatsResponse["quality_tiers"];
}

export default function QualityChart({ qualityTiers }: QualityChartProps) {
  const tiers = [
    { label: "Excellent (≥80)", value: qualityTiers.pct_80_plus || 0, color: "var(--accent-green)" },
    { label: "Good (70-79)", value: qualityTiers.pct_70_79 || 0, color: "var(--accent-cyan)" },
    { label: "Fair (60-69)", value: qualityTiers.pct_60_69 || 0, color: "var(--accent-yellow)" },
    { label: "Needs Work (<60)", value: qualityTiers.pct_below_60 || 0, color: "var(--accent-magenta)" },
  ];

  const maxValue = Math.max(...tiers.map(t => t.value), 1);

  return (
    <section style={{ marginBottom: "40px" }}>
      <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", marginBottom: 8, letterSpacing: "0.2em" }}>
        {"/// QUALITY_DISTRIBUTION"}
      </div>
      <div className="border-box" style={{ padding: "20px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {tiers.map((tier) => (
            <div key={tier.label}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: "4px", fontSize: "0.75rem" }}>
                <span style={{ color: tier.color, letterSpacing: "0.05em" }}>{tier.label}</span>
                <span style={{ color: "var(--text-primary)", fontFamily: "var(--font-mono)" }}>{tier.value.toFixed(1)}%</span>
              </div>
              <div style={{ width: "100%", height: "8px", background: "var(--bg-input)", position: "relative" }}>
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    height: "100%",
                    width: `${(tier.value / maxValue) * 100}%`,
                    background: tier.color,
                    transition: "width 0.5s ease-out",
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
