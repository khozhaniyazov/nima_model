# Phase 8: Evaluation Dashboard - Context

**Gathered:** 2026-04-05
**Status:** Ready for planning
**Source:** From ROADMAP.md and existing codebase analysis

<domain>

## Phase Boundary

Phase 8 delivers a Next.js dashboard at `/dashboard` that visualizes quality metrics, trends, top examples, and error patterns from the NIMA rendering pipeline.

**In Scope:**
- Quality metrics dashboard with score visualization
- Trend charts (renders/day, quality over time)
- Top examples showcase with video playback
- Error pattern visualization and tracking

**Out of Scope:**
- Backend API changes (already exists)
- User authentication
- Data export functionality

</domain>

<decisions>

## Implementation Decisions

### UI Framework (per stack)
- Next.js 16.1.6 with React 19.2.3 and Tailwind CSS 4.2.1
- Use existing nima-frontend structure

### Data Visualization
- Use recharts for trend charts (lightweight, works well with React)
- Quality scores displayed as percentage with color coding

### Dashboard Layout
- Single-page dashboard with sections for each metric category
- Responsive grid layout: 3 columns on desktop, 1 on mobile

### Video Playback
- Use native HTML5 video player
- Videos served from Flask backend at `/outputs/<video_file>`

### Error Pattern Display
- Table view with sortable columns
- Color-coded resolution status

</decisions>

<canonical_refs>

## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Backend API
- `app.py` lines 1530-1634 — `/stats` and `/stats/top-examples` endpoints

### Frontend Structure
- `nima-frontend/src/app/page.tsx` — existing main page as reference for UI patterns
- `nima-frontend/src/app/layout.tsx` — root layout

### Database Schema
- `database_schema.sql` — `requests`, `render_jobs`, `ai_evaluations`, `error_patterns` tables

### Previous Phase Plans
- `05-01-PLAN.md` lines 211-217 — existing /stats enhancement notes

</canonical_refs>

<specifics>

## Specific Ideas

1. **Quality Score Ranges**: Use color coding (green ≥80, yellow 60-79, red <60)
2. **Trend Period**: 7-day rolling window for renders/day and quality trends
3. **Top Examples Limit**: Show top 10 highest-scoring examples
4. **Error Patterns**: Show unresolved errors first, sorted by occurrence count

</specifics>

<deferred>

## Deferred Ideas

None — Phase 8 scope is fully defined by requirements M2-DASH-01 through M2-DASH-04

</deferred>

---

*Phase: 08-evaluation-dashboard*
*Context gathered: 2026-04-05*
