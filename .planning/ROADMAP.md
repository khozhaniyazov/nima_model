# NIMA Roadmap

**Created:** 2026-04-04
**Granularity:** Coarse (3-5 phases)
**Parallelization:** Enabled

---

## Phase 1: Foundation & Stability

**Goal:** Ensure the existing pipeline runs reliably with no flaky components.

### Requirements Mapped
- AUTH-01, GEN-01, GEN-02, GEN-03, GEN-04, GEN-05
- QUAL-01, QUAL-02, QUAL-03, QUAL-04
- HEAL-01, HEAL-02, HEAL-03
- MODE-01, MODE-02, MODE-03
- EXP-01, EXP-02

### Success Criteria
1. User can submit a prompt and receive a rendered video
2. Render pipeline completes without hanging or crashes
3. Status polling returns accurate progress information
4. Error messages are clear and actionable
5. FAST/DRAFT/FULL modes all function correctly

### Plans
- [ ] 1-01-PLAN.md — Fix critical bugs: is_fast scoping, video race, thread safety, validation gaps, Flask security, configurable paths

### Key Work
- Audit and fix any flaky components in the generation pipeline
- Ensure database fallbacks work gracefully when `USE_DATABASE=false`
- Verify all pipeline modes produce valid output
- Test short prompt expansion across edge cases

---

## Phase 2: Quality & Reliability

**Goal:** Reduce render retry rates by improving code generation and validation.

### Requirements Mapped
- LAY-01, LAY-02, LAY-03
- DOM-01, DOM-02, DOM-03, DOM-04
- RAG-01, RAG-02, RAG-03

### Success Criteria
1. Render success rate ≥ 90% on first attempt
2. Position collision detection catches all overlap issues
3. RAG retrieval provides relevant examples for each domain
4. All four domains (math, physics, CS, chemistry) produce valid animations

### Key Work
- Improve overlap detector with more comprehensive checks
- Expand RAG corpus with additional pattern examples
- Tune domain-specific guidance based on error patterns
- Add validation for section lifecycle helper usage

---

## Phase 3: Voiceover & Polish

**Goal:** Complete the voiceover pipeline and polish user experience.

### Requirements Mapped
- VOIC-01, VOIC-02, VOIC-03, VOIC-04

### Success Criteria
1. User can enable voiceover and receive narrated video
2. Audio timing synchronizes correctly with animation
3. TTS generates natural-sounding narration
4. Fallback to silent video works when TTS fails

### Key Work
- Test audio-video sync across different prompt lengths
- Improve narration quality with better segment timing
- Handle edge cases (empty segments, very long narration)
- Add voice selection options

---

## Phase 4: Evaluation & Learning

**Goal:** Build the quality tracking and continuous learning system.

### Requirements Mapped
- EVAL-01, EVAL-02, EVAL-03

### Success Criteria
1. Every successful render produces a quality score
2. Scores are visible via /stats endpoint
3. High-quality examples are retrievable for RAG
4. Error patterns are tracked and inform generation

### Key Work
- Ensure evaluation runs reliably on all successful renders
- Build quality score aggregation in /stats
- Verify high-scorer retrieval for future RAG queries
- Confirm error pattern recording and retrieval

---

## Phase 5: Production Hardening

**Goal:** Prepare NIMA for production deployment beyond localhost.

### Requirements Mapped
- V2-01 (partial: API rate limiting)
- V2-02 (batch processing)
- V2-04 (evaluation dashboard)

### Success Criteria
1. System handles concurrent requests without race conditions
2. Render jobs complete correctly under load
3. Stats endpoint returns accurate aggregate data
4. No secrets or credentials exposed in logs

### Key Work
- Add concurrent job management improvements
- Implement basic rate limiting
- Add comprehensive logging and monitoring
- Security audit of all endpoints

---

## Milestone 3: Video Hosting, Styling, Performance, API

### Phase 9: Video Hosting

**Goal:** Built-in video storage, playback, and CDN integration.

**Requirements:** M3-VID-01, M3-VID-02, M3-VID-03, M3-VID-04

**Success Criteria:**
1. Videos stored locally with organized structure
2. HTML5 video playback in web interface
3. CDN URL mapping for external hosting
4. Video search and metadata lookup

**Plans:** 3 plans

Plans:
- [ ] 09-01-PLAN.md — Video storage organization and metadata API
- [ ] 09-02-PLAN.md — CDN integration and VideoPlayer component
- [ ] 09-03-PLAN.md — Video library page with search and playback

---

### Phase 10: Custom Styling/Branding

**Goal:** Themes, watermarks, intro/outro animations.

**Requirements:** M3-STYLE-01, M3-STYLE-02, M3-STYLE-03, M3-STYLE-04

**Success Criteria:**
1. Theme system with light/dark/custom modes
2. Custom watermark support
3. Intro/outro animation templates
4. Custom color palette per video

---

### Phase 11: Performance Optimization

**Goal:** Faster renders through caching and parallel execution.

**Requirements:** M3-PERF-01, M3-PERF-02, M3-PERF-03, M3-PERF-04

**Success Criteria:**
1. Render caching reduces redundant renders
2. Parallel pipeline execution
3. Code generation caching
4. Asset preloading

---

### Phase 12: API/Integrations

**Goal:** Webhooks, LMS integration, public API.

**Requirements:** M3-API-01, M3-API-02, M3-API-03, M3-API-04

**Success Criteria:**
1. Webhook notifications on render complete
2. Canvas/Moodle LTI integration
3. API key authentication
4. Enhanced batch processing

---

## Roadmap Summary

| # | Phase | Goal | Requirements | Success Criteria |
|---|-------|------|--------------|------------------|
| 1 | Foundation & Stability | Reliable pipeline | 16 | Prompt → video, no crashes, graceful degradation |
| 2 | Quality & Reliability | Reduce retries | 9 | ≥90% first-attempt success, all domains work |
| 3 | Voiceover & Polish | Complete TTS pipeline | 4 | Narrated video with synced audio |
| 4 | Evaluation & Learning | Quality tracking | 3 | Scores visible, examples retrievable |
| 5 | Production Hardening | Deployment-ready | 3 | Concurrent requests, monitoring, security |
| 6 | Semantic RAG & Quality Prediction | Smart retrieval | 4 | Embedding-based RAG, quality prediction |
| 7 | Template Expansion | Domain coverage | 4 | All domains have rich templates |
| 8 | Evaluation Dashboard | Metrics visibility | 4 | Frontend dashboard for quality |
| 9 | Video Hosting | Video storage/playback | 4 | Local storage + CDN + search |
| 10 | Custom Styling/Branding | Themes + branding | 4 | Themes, watermarks, intro/outro |
| 11 | Performance Optimization | Faster renders | 4 | Caching + parallel execution |
| 12 | API/Integrations | Webhooks + LMS | 4 | Webhooks + API keys |

**Milestone 1:** All v1 requirements covered (5 phases) — COMPLETE  
**Milestone 2:** RAG v2, Templates, Dashboard (3 phases) — COMPLETE → [Archived](milestones/v2.0-ROADMAP.md)  
**Milestone 3:** Video Hosting, Styling, Performance, API (4 phases) — PENDING

---

*Roadmap created: 2026-04-04*
*Milestone 2 archived: 2026-04-05*
*Milestone 3 added: 2026-04-05*
