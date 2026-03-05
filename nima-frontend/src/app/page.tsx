"use client";

import { useState, useEffect, useRef, useCallback } from "react";

const API_BASE = "http://localhost:5000";

/* ── Types ──────────────────────────────────────────────────────── */
interface JobStatus {
  status: "generating" | "rendering" | "done" | "error" | "unknown";
  message: string;
  video_file?: string;
}

interface Stats {
  total_requests: number;
  successful_renders: number;
  avg_quality_score: number | null;
  unique_error_patterns: number;
}

/* ── HUD Geometric Decorations ───────────────────────────────────── */
function WireframeLoader() {
  return (
    <div style={{ width: 24, height: 24, position: "relative" }}>
      <svg viewBox="0 0 100 100" style={{ animation: "spin-slow 4s linear infinite" }}>
        <path d="M50 5 L95 25 L95 75 L50 95 L5 75 L5 25 Z" fill="none" stroke="currentColor" strokeWidth="3" />
        <path d="M5 25 L50 50 L95 25" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="4 4" />
        <path d="M50 50 L50 95" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="4 4" />
      </svg>
    </div>
  );
}

/* ── Edge Decorations ─────────────────────────────────────────── */
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

/* ── Main Page ──────────────────────────────────────────────────── */
export default function Home() {
  const [prompt, setPrompt] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [voiceover, setVoiceover] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<{ prompt: string; videoFile: string }[]>([]);
  const [examplePrompts, setExamplePrompts] = useState<string[]>([]);
  const [isFetchingPrompts, setIsFetchingPrompts] = useState(false);
  const [coords, setCoords] = useState({ x: "00.0000", y: "00.0000" });

  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  /* Fetch stats on mount */
  useEffect(() => {
    setCoords({
      x: (Math.random() * 100).toFixed(4),
      y: (Math.random() * 100).toFixed(4),
    });

    fetch(`${API_BASE}/stats`)
      .then((r) => r.json())
      .then((d) => {
        if (d.stats) setStats(d.stats);
      })
      .catch(() => { });
  }, []);

  const fetchPrompts = useCallback(async () => {
    setIsFetchingPrompts(true);
    try {
      const res = await fetch(`${API_BASE}/api/prompts?n=4`);
      const data = await res.json();
      if (data.prompts) setExamplePrompts(data.prompts);
    } catch {
      /* ignore */
    } finally {
      setIsFetchingPrompts(false);
    }
  }, []);

  useEffect(() => {
    fetchPrompts();
  }, [fetchPrompts]);

  /* Poll job status */
  const startPolling = useCallback(
    (id: string) => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      pollingRef.current = setInterval(async () => {
        try {
          const res = await fetch(`${API_BASE}/status/${id}`);
          const data: JobStatus = await res.json();
          setJobStatus(data);

          if (data.status === "done" || data.status === "error") {
            if (pollingRef.current) clearInterval(pollingRef.current);
            pollingRef.current = null;

            if (data.status === "done" && data.video_file) {
              setHistory((prev) => [
                { prompt, videoFile: data.video_file! },
                ...prev.slice(0, 4),
              ]);
            }
          }
        } catch {
          /* network drop */
        }
      }, 1500);
    },
    [prompt]
  );

  /* Cleanup polling on unmount */
  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, []);

  /* Submit prompt */
  const handleSubmit = async () => {
    const trimmed = prompt.trim();
    if (!trimmed || isSubmitting) return;
    setError(null);
    setIsSubmitting(true);
    setJobStatus(null);
    setJobId(null);

    try {
      const res = await fetch(`${API_BASE}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: trimmed, voiceover }),
      });
      const data = await res.json();

      if (!res.ok) {
        setError(data.error || "FATAL_ERROR: CONNECTION_REFUSED");
        setIsSubmitting(false);
        return;
      }

      setJobId(data.job_id);
      setJobStatus({
        status: "generating",
        message: "INITIATING COMPILER SEQUENCE...",
      });
      startPolling(data.job_id);
    } catch {
      setError("SYS_ERROR: BACKEND_UNREACHABLE");
    } finally {
      setIsSubmitting(false);
    }
  };

  const videoUrl =
    jobStatus?.status === "done" && jobStatus.video_file
      ? `${API_BASE}/outputs/${jobStatus.video_file}`
      : null;

  return (
    <>
      <div className="blueprint-grid" />
      <div className="crosshair crosshair-h" />
      <div className="crosshair crosshair-v" />
      <div className="scanline-overlay" />

      <div style={{ position: "relative", zIndex: 10, minHeight: "100vh", display: "flex", flexDirection: "column", padding: "40px" }}>

        {/* ── Header Area ── */}
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: "60px" }}>
          <div style={{ display: "flex", gap: "24px" }}>
            <div style={{ width: "48px", height: "48px", border: "2px solid var(--accent-cyan)", display: "flex", alignItems: "center", justifyContent: "center", position: "relative" }}>
              <div style={{ width: "16px", height: "16px", background: "var(--accent-cyan)" }} className="animate-pulse-op" />
              <div style={{ position: "absolute", top: -8, right: -8, width: 4, height: 4, background: "var(--accent-magenta)" }} />
            </div>
            <div>
              <h1 className="font-display font-bold" style={{ fontSize: "2.5rem", lineHeight: 1, letterSpacing: "-0.02em", color: "var(--text-primary)" }}>
                NIMA <span style={{ color: "var(--text-muted)", fontSize: "1.5rem" }}>SYS.V1</span>
              </h1>
              <div style={{ fontSize: "0.75rem", color: "var(--accent-cyan)", marginTop: "8px", letterSpacing: "0.2em" }}>
                [ AI_ANIMATION_ENGINE_ACTIVE ]
              </div>
            </div>
          </div>

          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>
            <div>COORD_X: {coords.x}</div>
            <div>COORD_Y: {coords.y}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 12, color: "var(--text-primary)" }}>
              STATUS: <span style={{ display: "inline-block", width: 8, height: 8, background: "var(--accent-green)", border: "1px solid #fff" }} /> ONLINE
            </div>
          </div>
        </header>

        {/* ── Telemetry / Stats ── */}
        {stats && (
          <section className="animate-glitch" style={{ marginBottom: "40px" }}>
            <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", marginBottom: 8, letterSpacing: "0.2em" }}>/// SYSTEM_TELEMETRY</div>
            <div className="data-grid">
              <div className="data-cell">
                <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>TOTAL_REQ</div>
                <div className="text-cyan font-display" style={{ fontSize: "1.8rem", fontWeight: 700 }}>{stats.total_requests.toString().padStart(4, "0")}</div>
              </div>
              <div className="data-cell">
                <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>SUCCESS_VOL</div>
                <div className="text-green font-display" style={{ fontSize: "1.8rem", fontWeight: 700 }}>{stats.successful_renders.toString().padStart(4, "0")}</div>
              </div>
              <div className="data-cell">
                <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>QUAL_INDEX</div>
                <div className="font-display" style={{ fontSize: "1.8rem", fontWeight: 700, color: "var(--text-primary)" }}>
                  {stats.avg_quality_score ? (stats.avg_quality_score / 100).toFixed(2) : "N/A"}
                </div>
              </div>
              <div className="data-cell">
                <div style={{ fontSize: "0.7rem", color: "var(--text-secondary)", letterSpacing: "0.1em" }}>ERR_PATTERNS</div>
                <div className="text-magenta font-display" style={{ fontSize: "1.8rem", fontWeight: 700 }}>{stats.unique_error_patterns.toString().padStart(2, "0")}</div>
              </div>
            </div>
          </section>
        )}

        <div style={{ display: "grid", gridTemplateColumns: "1fr 400px", gap: "40px", flex: 1 }}>

          {/* left column: Input */}
          <section>
            <div className="border-box" style={{ padding: 1, height: "100%", display: "flex", flexDirection: "column" }}>
              <Corners />

              {/* Box Header */}
              <div style={{ borderBottom: "1px solid var(--border-strong)", padding: "12px 20px", display: "flex", justifyContent: "space-between", background: "rgba(0, 240, 255, 0.05)" }}>
                <span style={{ fontSize: "0.75rem", color: "var(--accent-cyan)", letterSpacing: "0.1em" }}>INPUT_TERMINAL</span>
                <span className="animate-blink" style={{ width: 6, height: 12, background: "var(--accent-cyan)", display: "inline-block" }} />
              </div>

              <div style={{ padding: "24px", flex: 1, display: "flex", flexDirection: "column", gap: "24px" }}>
                <textarea
                  ref={textareaRef}
                  className="technical-input"
                  rows={6}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit();
                  }}
                  placeholder="> INJECT MANIM DIRECTIVE HERE..."
                />

                {/* ── Example Prompts ── */}
                <div style={{ display: "flex", flexDirection: "column", gap: "12px", marginTop: "-8px" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ fontSize: "0.65rem", color: "var(--text-secondary)", letterSpacing: "0.15em", display: "flex", alignItems: "center", gap: "8px" }}>
                      <span style={{ width: 4, height: 4, background: "var(--accent-cyan)", display: "inline-block" }} />
                      SUGGESTED_DIRECTIVES
                    </div>
                    <button
                      onClick={fetchPrompts}
                      disabled={isFetchingPrompts}
                      className="btn-refresh hover-glitch-text"
                    >
                      {isFetchingPrompts ? "[ REFRESHING... ]" : "[ REFRESH_SEQ ]"}
                    </button>
                  </div>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "8px" }}>
                    {examplePrompts.map((p, idx) => (
                      <div
                        key={idx}
                        onClick={() => setPrompt(p)}
                        className="prompt-template-card"
                      >
                        <div className="card-accent" />
                        <span style={{ color: "var(--accent-cyan)", marginRight: "6px" }}>{`>_`}</span>
                        {p}
                      </div>
                    ))}
                  </div>
                </div>

                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderTop: "1px dashed var(--border-strong)", paddingTop: "24px" }}>

                  <label style={{ display: "flex", alignItems: "center", gap: 12, cursor: "pointer", fontSize: "0.85rem", letterSpacing: "0.05em" }}>
                    <input
                      type="checkbox"
                      className="brutal-checkbox"
                      checked={voiceover}
                      onChange={(e) => setVoiceover(e.target.checked)}
                    />
                    <span style={{ color: voiceover ? "var(--text-primary)" : "var(--text-muted)" }}>ENABLE_VOICEOVER_MANDATE</span>
                  </label>

                  <button className="btn-brutal" onClick={handleSubmit} disabled={!prompt.trim() || isSubmitting}>
                    {isSubmitting ? (
                      <><span style={{ color: "var(--accent-cyan)" }}>[</span> <WireframeLoader /> EXECUTING <span style={{ color: "var(--accent-cyan)" }}>]</span></>
                    ) : (
                      <><span style={{ color: "var(--accent-cyan)" }}>[</span> DEPLOY COMPILE <span style={{ color: "var(--accent-cyan)" }}>]</span></>
                    )}
                  </button>

                </div>

                {error && (
                  <div style={{ marginTop: "16px", padding: "16px", border: "1px solid var(--accent-magenta)", background: "var(--accent-magenta-dim)", color: "var(--accent-magenta)", fontSize: "0.85rem", letterSpacing: "0.05em" }}>
                    [ERR_CRITICAL]: {error}
                  </div>
                )}
              </div>
            </div>
          </section>

          {/* right column: Status Monitor & Video */}
          <section style={{ display: "flex", flexDirection: "column", gap: "24px" }}>

            <div className="border-box" style={{ padding: "20px" }}>
              <Corners />
              <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", letterSpacing: "0.1em", marginBottom: 16 }}>MONITOR // THREAD_0</div>

              {!jobStatus ? (
                <div style={{ padding: "40px 20px", textAlign: "center", color: "var(--text-muted)", fontSize: "0.8rem", letterSpacing: "0.1em" }}>
                  AWAITING_TASKS...
                </div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--text-primary)" }}>{jobStatus.status.toUpperCase()}</div>
                    {(jobStatus.status === "generating" || jobStatus.status === "rendering") && <WireframeLoader />}
                  </div>

                  <div style={{ width: "100%", height: "2px", background: "var(--bg-input)", position: "relative" }}>
                    <div style={{
                      position: "absolute", top: 0, left: 0, height: "100%",
                      background: jobStatus.status === "error" ? "var(--accent-magenta)" : jobStatus.status === "done" ? "var(--accent-green)" : "var(--accent-cyan)",
                      width: jobStatus.status === "generating" ? "30%" : jobStatus.status === "rendering" ? "70%" : "100%",
                      transition: "width 0.4s cubic-bezier(0.2,0.8,0.2,1)"
                    }} />
                  </div>

                  <div style={{ fontSize: "0.75rem", color: "var(--text-secondary)", fontFamily: "var(--font-mono)", lineHeight: 1.5 }}>
                    <span className="text-cyan">{">"}</span> {jobStatus.message}
                  </div>

                  {jobId && (
                    <div style={{ fontSize: "0.65rem", color: "var(--text-muted)", borderTop: "1px solid var(--border-grid)", paddingTop: 8 }}>
                      ID: {jobId}
                    </div>
                  )}

                </div>
              )}
            </div>

            {videoUrl && (
              <div className="border-box animate-fade-in-up" style={{ padding: "16px", flex: 1 }}>
                <Corners />
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
                  <span style={{ fontSize: "0.75rem", color: "var(--accent-green)", letterSpacing: "0.1em" }}>OUTPUT_RENDERED</span>
                  <a href={videoUrl} download style={{ color: "var(--text-primary)", fontSize: "0.75rem", textDecoration: "none", borderBottom: "1px solid var(--accent-green)" }}>
                    [ DL_ASSET ]
                  </a>
                </div>

                <div className="video-frame">
                  <video
                    controls
                    autoPlay
                    loop
                    src={videoUrl}
                    style={{ width: "100%", height: "auto", display: "block" }}
                  />
                </div>
              </div>
            )}

          </section>

        </div>
      </div>
    </>
  );
}
