"use client";

import { useState, useEffect } from "react";
import { fetchStats, fetchTopExamples, StatsResponse, TopExample } from "@/lib/api";
import StatsGrid from "@/components/dashboard/StatsGrid";
import QualityChart from "@/components/dashboard/QualityChart";
import TrendChart from "@/components/dashboard/TrendChart";
import TopExamples from "@/components/dashboard/TopExamples";
import ErrorPatterns from "@/components/dashboard/ErrorPatterns";

function Corners() {
  return (
    <div className="corners-wrapper">
      <div className="corner-accent corner-tl" />
      <div className="corner-accent corner-tr" />
      <div className="corner-accent corner-bl" />
      <div className="corner-accent corner-br" />
    </div>
  );
}

function generateMockTrendData(): Array<{ date: string; renders: number; avgQuality: number }> {
  const data = [];
  for (let i = 6; i >= 0; i--) {
    const date = new Date();
    date.setDate(date.getDate() - i);
    data.push({
      date: date.toISOString(),
      renders: Math.floor(Math.random() * 20) + 5,
      avgQuality: Math.floor(Math.random() * 20) + 70,
    });
  }
  return data;
}

export default function Dashboard() {
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [topExamples, setTopExamples] = useState<TopExample[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadData = async () => {
      try {
        const [statsData, examplesData] = await Promise.all([
          fetchStats(),
          fetchTopExamples(),
        ]);
        setStats(statsData);
        setTopExamples(examplesData.top_examples || []);
        setError(null);
      } catch {
        setError("FAILED_TO_CONNECT");
      } finally {
        setLoading(false);
      }
    };

    loadData();
    const interval = setInterval(loadData, 60000);
    return () => clearInterval(interval);
  }, []);

  return (
    <>
      <div className="blueprint-grid" />
      <div className="crosshair crosshair-h" />
      <div className="crosshair crosshair-v" />
      <div className="scanline-overlay" />

      <div style={{ position: "relative", zIndex: 10, minHeight: "100vh", padding: "40px" }}>
        {/* Header */}
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "60px" }}>
          <div style={{ display: "flex", gap: "24px" }}>
            <div style={{ width: "48px", height: "48px", border: "2px solid var(--accent-cyan)", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
              <div style={{ width: "16px", height: "16px", background: "var(--accent-cyan)" }} className="animate-pulse-op" />
            </div>
            <div>
              <h1 className="font-display" style={{ fontSize: "2.5rem", lineHeight: 1, letterSpacing: "-0.02em", color: "var(--text-primary)" }}>
                EVALUATION_DASHBOARD <span style={{ color: "var(--text-muted)", fontSize: "1.5rem" }}>SYS.V1</span>
              </h1>
              <div style={{ fontSize: "0.75rem", color: "var(--accent-cyan)", marginTop: "8px", letterSpacing: "0.2em" }}>
                [ QUALITY_METRICS_ANALYTICS_ACTIVE ]
              </div>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>
            <div>MODE: ANALYTICS</div>
            <div style={{ marginTop: 8, display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ display: "inline-block", width: 8, height: 8, background: loading ? "var(--accent-yellow)" : "var(--accent-green)", border: "1px solid #fff" }} />
              {loading ? "LOADING..." : "LIVE"}
            </div>
          </div>
        </header>

        {error && (
          <div style={{ marginBottom: "40px", padding: "16px", border: "1px solid var(--accent-magenta)", background: "var(--accent-magenta-dim)", color: "var(--accent-magenta)", fontSize: "0.85rem", letterSpacing: "0.05em" }}>
            [ERR_CRITICAL]: {error}
          </div>
        )}

        {stats && (
          <main>
            <StatsGrid
              stats={stats.stats}
              rendersToday={stats.renders_today}
              lastRenderAt={stats.last_render_at}
            />

            {/* Row 2: Quality + Trend */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "24px", marginBottom: "40px" }}>
              <QualityChart qualityTiers={stats.quality_tiers} />
              <TrendChart dailyData={generateMockTrendData()} />
            </div>

            {/* Quality Dimensions */}
            <section style={{ marginBottom: "40px" }}>
              <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", marginBottom: 8, letterSpacing: "0.2em" }}>
                {"/// QUALITY_DIMENSIONS"}
              </div>
              <div className="border-box" style={{ padding: "20px" }}>
                <Corners />
                <div className="data-grid">
                  <div className="data-cell">
                    <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>LAYOUT</div>
                    <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
                      {stats.quality_dims.avg_layout.toFixed(1)}
                    </div>
                  </div>
                  <div className="data-cell">
                    <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>EDUCATIONAL</div>
                    <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
                      {stats.quality_dims.avg_educational.toFixed(1)}
                    </div>
                  </div>
                  <div className="data-cell">
                    <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>TECHNICAL</div>
                    <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
                      {stats.quality_dims.avg_technical.toFixed(1)}
                    </div>
                  </div>
                  <div className="data-cell">
                    <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>PACING</div>
                    <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
                      {stats.quality_dims.avg_pacing.toFixed(1)}
                    </div>
                  </div>
                  <div className="data-cell">
                    <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>MANIM_QUALITY</div>
                    <div style={{ fontSize: "1.4rem", fontWeight: 700, color: "var(--accent-cyan)" }}>
                      {stats.quality_dims.avg_manim.toFixed(1)}
                    </div>
                  </div>
                </div>
              </div>
            </section>

            {/* Row 3: Top Examples + Error Patterns */}
            <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: "24px", marginBottom: "40px" }}>
              <TopExamples examples={topExamples} />
              <ErrorPatterns errors={stats.top_errors} />
            </div>
          </main>
        )}
      </div>
    </>
  );
}
