"use client";

import { StatsResponse } from "@/lib/api";

interface ErrorPatternsProps {
  errors: StatsResponse["top_errors"];
}

function getCountBadgeColor(count: number): string {
  if (count > 10) return "var(--accent-magenta)";
  if (count >= 5) return "var(--accent-yellow)";
  return "var(--accent-cyan)";
}

export default function ErrorPatterns({ errors }: ErrorPatternsProps) {
  if (errors.length === 0) {
    return (
      <section>
        <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", marginBottom: 8, letterSpacing: "0.2em" }}>
          {"/// ERROR_PATTERNS_TRACKED"}
        </div>
        <div className="border-box" style={{ padding: "40px", textAlign: "center" }}>
          <div style={{ color: "var(--text-muted)", fontSize: "0.85rem", letterSpacing: "0.1em" }}>
            NO_ERROR_PATTERNS
          </div>
          <div style={{ color: "var(--text-muted)", fontSize: "0.7rem", marginTop: "8px", letterSpacing: "0.05em" }}>
            Error patterns will appear here as renders fail and get categorized
          </div>
        </div>
      </section>
    );
  }

  const sortedErrors = [...errors].sort((a, b) => b.occurrence_count - a.occurrence_count);

  return (
    <section>
      <div style={{ fontSize: "0.6rem", color: "var(--text-muted)", marginBottom: 8, letterSpacing: "0.2em" }}>
        {"/// ERROR_PATTERNS_TRACKED"}
      </div>
      <div className="border-box" style={{ padding: 0, overflow: "hidden" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
          <thead>
            <tr style={{ background: "var(--bg-input)", borderBottom: "1px solid var(--border-strong)" }}>
              <th style={{ padding: "12px 16px", textAlign: "left", color: "var(--text-muted)", fontWeight: 400, letterSpacing: "0.1em" }}>
                CATEGORY
              </th>
              <th style={{ padding: "12px 16px", textAlign: "left", color: "var(--text-muted)", fontWeight: 400, letterSpacing: "0.1em" }}>
                ROOT_CAUSE
              </th>
              <th style={{ padding: "12px 16px", textAlign: "center", color: "var(--text-muted)", fontWeight: 400, letterSpacing: "0.1em" }}>
                COUNT
              </th>
              <th style={{ padding: "12px 16px", textAlign: "left", color: "var(--text-muted)", fontWeight: 400, letterSpacing: "0.1em" }}>
                FIX
              </th>
            </tr>
          </thead>
          <tbody>
            {sortedErrors.map((error, i) => (
              <tr
                key={i}
                style={{ borderBottom: i < sortedErrors.length - 1 ? "1px solid var(--border-grid)" : "none", background: i % 2 === 0 ? "transparent" : "var(--bg-input)" }}
              >
                <td style={{ padding: "12px 16px" }}>
                  <span
                    style={{
                      padding: "2px 8px",
                      border: "1px solid var(--accent-magenta)",
                      color: "var(--accent-magenta)",
                      fontSize: "0.7rem",
                      letterSpacing: "0.05em",
                    }}
                  >
                    {error.error_category.toUpperCase()}
                  </span>
                </td>
                <td style={{ padding: "12px 16px", color: "var(--text-secondary)", maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {error.root_cause}
                </td>
                <td style={{ padding: "12px 16px", textAlign: "center" }}>
                  <span
                    style={{
                      padding: "2px 8px",
                      border: `1px solid ${getCountBadgeColor(error.occurrence_count)}`,
                      color: getCountBadgeColor(error.occurrence_count),
                      fontSize: "0.75rem",
                      fontWeight: 700,
                    }}
                  >
                    {error.occurrence_count}
                  </span>
                </td>
                <td style={{ padding: "12px 16px", color: "var(--text-muted)", fontSize: "0.75rem", maxWidth: "200px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {error.fix_description}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
