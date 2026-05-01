"use client";

interface TrendChartProps {
  dailyData: Array<{ date: string; renders: number; avgQuality: number }>;
}

export default function TrendChart({ dailyData }: TrendChartProps) {
  const maxRenders = Math.max(...dailyData.map(d => d.renders), 1);
  const maxQuality = 100;

  const formatDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr);
      return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    } catch {
      return dateStr;
    }
  };

  return (
    <section style={{ marginBottom: "40px" }}>
      <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", marginBottom: 8, letterSpacing: "0.2em" }}>
        {"/// RENDER_TRENDS (7D)"}
      </div>
      <div className="border-box" style={{ padding: "20px" }}>
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
          {/* Legend */}
          <div style={{ display: "flex", gap: "24px", fontSize: "0.75rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: 12, height: 3, background: "var(--accent-cyan)" }} />
              <span style={{ color: "var(--text-secondary)" }}>RENDERS</span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <div style={{ width: 12, height: 3, background: "var(--accent-green)" }} />
              <span style={{ color: "var(--text-secondary)" }}>AVG_QUALITY</span>
            </div>
          </div>

          {/* Chart */}
          <div style={{ position: "relative", height: "120px" }}>
            {/* Y-axis labels */}
            <div style={{ position: "absolute", left: 0, top: 0, fontSize: "0.65rem", color: "var(--text-muted)" }}>
              {maxRenders}
            </div>
            <div style={{ position: "absolute", left: 0, bottom: 0, fontSize: "0.65rem", color: "var(--text-muted)" }}>
              0
            </div>

            {/* Bars and line overlay */}
            <div style={{ position: "absolute", left: "30px", right: 0, top: 0, bottom: "20px", display: "flex", alignItems: "flex-end", gap: "8px" }}>
              {dailyData.map((d, i) => {
                const barHeight = (d.renders / maxRenders) * 100;
                const qualityHeight = (d.avgQuality / maxQuality) * 100;
                const isWeekend = new Date(d.date).getDay() === 0 || new Date(d.date).getDay() === 6;
                
                return (
                  <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: "4px", height: "100%", position: "relative" }}>
                    {/* Quality line point */}
                    <div
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: "var(--accent-green)",
                        position: "absolute",
                        bottom: `${qualityHeight}%`,
                        zIndex: 2,
                      }}
                    />
                    {/* Render bar */}
                    <div
                      style={{
                        width: "100%",
                        height: `${barHeight}%`,
                        background: isWeekend ? "var(--accent-magenta-dim)" : "var(--accent-cyan-dim)",
                        border: `1px solid ${isWeekend ? "var(--accent-magenta)" : "var(--accent-cyan)"}`,
                        position: "absolute",
                        bottom: 0,
                        transition: "height 0.3s ease-out",
                      }}
                    />
                  </div>
                );
              })}
            </div>

            {/* X-axis labels */}
            <div style={{ position: "absolute", left: "30px", right: 0, bottom: 0, display: "flex", justifyContent: "space-around" }}>
              {dailyData.map((d, i) => (
                <div key={i} style={{ fontSize: "0.6rem", color: "var(--text-muted)", textAlign: "center", flex: 1 }}>
                  {formatDate(d.date)}
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
