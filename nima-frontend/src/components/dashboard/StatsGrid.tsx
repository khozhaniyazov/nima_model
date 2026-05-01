"use client";

import { StatsResponse } from "@/lib/api";

interface StatsGridProps {
  stats: StatsResponse["stats"];
  rendersToday: number;
  lastRenderAt: string;
}

export default function StatsGrid({ stats, rendersToday, lastRenderAt }: StatsGridProps) {
  const formatDate = (dateStr: string) => {
    if (!dateStr) return "N/A";
    try {
      return new Date(dateStr).toLocaleString();
    } catch {
      return "N/A";
    }
  };

  const getQualityColor = (score: number | null) => {
    if (score === null) return "var(--text-muted)";
    if (score >= 80) return "var(--accent-green)";
    if (score >= 60) return "var(--accent-cyan)";
    return "var(--accent-magenta)";
  };

  return (
    <section style={{ marginBottom: "40px" }}>
      <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", marginBottom: 8, letterSpacing: "0.2em" }}>
        {"/// SYSTEM_TELEMETRY"}
      </div>
      <div className="data-grid">
        <div className="data-cell">
          <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>TOTAL_REQ</div>
          <div className="text-cyan font-display" style={{ fontSize: "1.8rem", fontWeight: 700 }}>
            {stats.total_requests.toString().padStart(4, "0")}
          </div>
        </div>
        <div className="data-cell">
          <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>SUCCESS_VOL</div>
          <div className="text-green font-display" style={{ fontSize: "1.8rem", fontWeight: 700 }}>
            {stats.successful_renders.toString().padStart(4, "0")}
          </div>
        </div>
        <div className="data-cell">
          <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>SUCCESS_RATE</div>
          <div className="font-display" style={{ fontSize: "1.8rem", fontWeight: 700, color: stats.success_rate >= 80 ? "var(--accent-green)" : stats.success_rate >= 50 ? "var(--accent-cyan)" : "var(--accent-magenta)" }}>
            {stats.success_rate.toFixed(1)}%
          </div>
        </div>
        <div className="data-cell">
          <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>QUAL_INDEX</div>
          <div className="font-display" style={{ fontSize: "1.8rem", fontWeight: 700, color: getQualityColor(stats.avg_quality_score ? stats.avg_quality_score : null) }}>
            {stats.avg_quality_score ? (stats.avg_quality_score / 100).toFixed(2) : "N/A"}
          </div>
        </div>
        <div className="data-cell">
          <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>RENDERS_TODAY</div>
          <div className="text-green font-display" style={{ fontSize: "1.8rem", fontWeight: 700 }}>
            {rendersToday.toString().padStart(3, "0")}
          </div>
        </div>
        <div className="data-cell">
          <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>ERR_PATTERNS</div>
          <div className="text-magenta font-display" style={{ fontSize: "1.8rem", fontWeight: 700 }}>
            {stats.unique_error_patterns.toString().padStart(2, "0")}
          </div>
        </div>
      </div>
      <div style={{ marginTop: "12px", fontSize: "0.65rem", color: "var(--text-muted)", letterSpacing: "0.1em" }}>
        LAST_RENDER: {formatDate(lastRenderAt)}
      </div>
    </section>
  );
}
