# NIMA Requirements

**Analysis Date:** 2026-04-04

## v1 Requirements

### Authentication

- [ ] **AUTH-01**: User can access the web interface without authentication (localhost-only deployment)

### Animation Generation

- [ ] **GEN-01**: User can submit a natural language prompt describing an educational animation
- [ ] **GEN-02**: System generates Manim Python code from the prompt using AI
- [ ] **GEN-03**: System renders the generated code to an MP4 video
- [ ] **GEN-04**: User can poll job status and receive progress updates
- [ ] **GEN-05**: User can download the rendered video

### Code Quality

- [ ] **QUAL-01**: Generated code passes Python syntax validation
- [ ] **QUAL-02**: Generated code passes Manim structure validation (class GeneratedScene, self.play)
- [ ] **QUAL-03**: Generated code passes security validation (no forbidden imports/calls)
- [ ] **QUAL-04**: Math domain LaTeX strings are validated before rendering

### Self-Healing

- [ ] **HEAL-01**: Render errors are parsed and categorized
- [ ] **HEAL-02**: Failed renders trigger LLM-powered error fixing
- [ ] **HEAL-03**: System retries rendering up to 3 times with automatic fixes

### Domain Support

- [ ] **DOM-01**: Math domain animations work with deterministic plan compiler
- [ ] **DOM-02**: Physics domain animations with appropriate visualizations (arrows, fields)
- [ ] **DOM-03**: Computer Science domain animations (arrays, trees, graphs)
- [ ] **DOM-04**: Chemistry domain animations (molecules, reactions)

### Voiceover

- [ ] **VOIC-01**: User can enable TTS voiceover narration
- [ ] **VOIC-02**: Narration segments are generated using OpenAI TTS
- [ ] **VOIC-03**: Audio and video are merged with synchronized timing
- [ ] **VOIC-04**: Audio duration drives animation timing (timing contract)

### RAG System

- [ ] **RAG-01**: Golden examples are retrieved based on domain/topic matching
- [ ] **RAG-02**: High-quality past examples (≥80 score) are retrievable
- [ ] **RAG-03**: Error patterns inform future generation to avoid repeated mistakes

### Quality Evaluation

- [ ] **EVAL-01**: Rendered animations are scored on quality dimensions
- [ ] **EVAL-02**: Evaluation scores are stored in the database
- [ ] **EVAL-03**: Quality metrics are visible via /stats endpoint

### Pipeline Modes

- [ ] **MODE-01**: FULL pipeline mode for production quality renders
- [ ] **MODE-02**: FAST pipeline mode for quick iteration
- [ ] **MODE-03**: DRAFT pipeline mode for ultra-fast preview

### Short Prompt Expansion

- [ ] **EXP-01**: Truncated prompts (ending in "...") are detected and expanded
- [ ] **EXP-02**: Problem-statement prompts (solve, compute, find) are expanded with visual guidance

### Layout Validation

- [ ] **LAY-01**: Position collisions are detected before rendering
- [ ] **LAY-02**: Object accumulation issues are detected
- [ ] **LAY-03**: Section cleanup helpers are validated for multi-step scenes

## v2 Requirements (Deferred)

- [ ] **V2-01**: User authentication and account management
- [ ] **V2-02**: Batch processing for multiple animation requests
- [ ] **V2-03**: Video hosting/integration options
- [ ] **V2-04**: Evaluation dashboard with analytics
- [ ] **V2-05**: Custom styling and branding options

## Out of Scope

- **3D Animations** — Manim CE 2D focus is intentional; 3D would fragment the codebase
- **Real-Time Collaborative Editing** — Single prompt → single video is the core workflow
- **Native Mobile App** — Web-only is correct priority; responsive web covers mobile viewing
- **Auto-Deployment** — Manual deployment is acceptable for target users
- **Video Hosting** — Users download and upload to their platform of choice
- **User Authentication** — No multi-user features; rate limiting via API key is sufficient
- **Generated Video Editing** — Against the "single prompt → complete video" simplicity
- **Real-Time Generation Streaming** — Manim rendering is inherently batch
- **Multiple Animation Styles** — 3b1b-style is the brand; custom themes would dilute quality

## Traceability

| Requirement | Phase | Success Criteria |
|-------------|-------|------------------|
| GEN-01, GEN-02, GEN-03 | Phase 1 | Prompt → rendered video end-to-end |
| QUAL-01, QUAL-02, QUAL-03, HEAL-01, HEAL-02, HEAL-03 | Phase 2 | Self-healing works for common errors |
| DOM-01 | Phase 3 | Math domain uses deterministic compiler |
| VOIC-01, VOIC-02, VOIC-03, VOIC-04 | Phase 4 | Narrated video with synced audio |
| RAG-01, RAG-02, RAG-03 | Phase 5 | RAG improves generation quality |
| EVAL-01, EVAL-02, EVAL-03 | Phase 6 | Quality scores visible and tracked |

---

*Requirements defined: 2026-04-04*
