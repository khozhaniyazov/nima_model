# NIMA Requirements

**Analysis Date:** 2026-04-05  
**Milestone:** 3 - Video Hosting, Styling, Performance, API

---

## Milestone 1 & 2 Requirements (Archived)

All requirements from Milestone 1 and 2 are archived in their respective milestone folders:
- v1.0-REQUIREMENTS.md
- v2.0-REQUIREMENTS.md

---

## Milestone 3 Requirements

### Video Hosting (M3-VID)

- [ ] **M3-VID-01**: Local video storage with organized directory structure
  - Videos stored in organized folders by date/domain
  - Metadata database for video lookup

- [ ] **M3-VID-02**: Video playback within the web interface
  - HTML5 video player with controls
  - Video preview thumbnails

- [ ] **M3-VID-03**: CDN integration for faster video delivery
  - Support for external CDN URLs
  - Video URL mapping/transformation

- [ ] **M3-VID-04**: Video metadata and search capabilities
  - Search by prompt, domain, date
  - Filter and sort video library

---

### Custom Styling/Branding (M3-STYLE)

- [ ] **M3-STYLE-01**: Theme system
  - Light/dark mode toggle
  - Custom theme support (colors, fonts)
  - Blueprint theme (current default)

- [ ] **M3-STYLE-02**: Watermark/logo customization
  - Add custom watermark to rendered videos
  - Position and opacity controls
  - Disable watermark option

- [ ] **M3-STYLE-03**: Intro/outro animation templates
  - Custom intro animation with branding
  - Custom outro animation with credits
  - Logo reveal animation

- [ ] **M3-STYLE-04**: Custom color palette support
  - User-defined accent colors
  - Per-video theme overrides
  - Theme presets

---

### Performance Optimization (M3-PERF)

- [ ] **M3-PERF-01**: Render caching
  - Cache rendered videos by code hash
  - Skip re-renders for identical code
  - Cache invalidation strategy

- [ ] **M3-PERF-02**: Parallel pipeline execution
  - Concurrent code generation and validation
  - Multi-threaded rendering where possible
  - Resource pool management

- [ ] **M3-PERF-03**: Code generation caching
  - Cache AI responses for similar prompts
  - Semantic cache for prompt variations
  - Cache hit rate metrics

- [ ] **M3-PERF-04**: Asset preloading and optimization
  - Preload common assets (axes, planes)
  - Optimize LaTeX compilation
  - Reduce scene initialization time

---

### API/Integrations (M3-API)

- [ ] **M3-API-01**: Webhook notifications
  - POST callback on render complete
  - Configurable webhook URL per request
  - Retry logic for failed webhooks

- [ ] **M3-API-02**: LMS integration API
  - Canvas LMS integration
  - Moodle integration
  - LTI support for embedding

- [ ] **M3-API-03**: Public API with key authentication
  - API key generation and management
  - Rate limiting per API key
  - Usage tracking and quotas

- [ ] **M3-API-04**: Batch processing improvements
  - Enhanced batch endpoint
  - Batch status polling
  - Batch progress notifications

---

## Out of Scope

- **Native mobile app** — Web-only is correct priority
- **Real-time collaborative editing** — Single prompt → single video
- **3D animations** — 2D Manim CE focus
- **Auto-deployment** — Manual deployment acceptable

---

## Traceability

| Requirement | Phase | Success Criteria |
|-------------|-------|------------------|
| M3-VID-01, M3-VID-02 | Phase 9 | Video playback works |
| M3-VID-03, M3-VID-04 | Phase 9 | CDN + search functional |
| M3-STYLE-01, M3-STYLE-02 | Phase 10 | Theme + watermark |
| M3-STYLE-03, M3-STYLE-04 | Phase 10 | Intro/outro + palette |
| M3-PERF-01, M3-PERF-02 | Phase 11 | Caching + parallel |
| M3-PERF-03, M3-PERF-04 | Phase 11 | Code cache + preload |
| M3-API-01, M3-API-02 | Phase 12 | Webhooks + LMS |
| M3-API-03, M3-API-04 | Phase 12 | API keys + batch |

---

*Requirements defined: 2026-04-05 for Milestone 3*
