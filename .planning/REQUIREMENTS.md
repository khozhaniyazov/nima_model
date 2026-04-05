# NIMA Requirements

**Analysis Date:** 2026-04-05  
**Milestone:** 4 - Streaming Generation

---

## Milestone 4 Requirements

### Streaming Generation (M4-STREAM)

- [ ] **M4-STREAM-01**: Scene-by-scene streaming generation
  - Split storyboard plan into individual scenes
  - Generate one scene at a time with narrative context
  - Each scene generates < 30s (vs 200s+ for full video)

- [ ] **M4-STREAM-02**: Parallel render-while-generate pipeline
  - Render scene N while generating scene N+1
  - Overlap render and generation for speed
  - ThreadPoolExecutor for parallel scene rendering

- [ ] **M4-STREAM-03**: Narrative context preservation
  - Track object state across scenes
  - Each scene preamble recreates needed objects
  - Viewer cannot tell scenes were generated separately

- [ ] **M4-STREAM-04**: Scene-level retry
  - Failed scene regenerates without full pipeline restart
  - Error feedback to LLM for targeted fix
  - Max 3 retries per scene

### Code Quality (M4-CODE)

- [ ] **M4-CODE-01**: Valid Manim API generation
  - No invalid calls like `start_section()`, `begin_section()`
  - Prompt includes valid API reference
  - Validation catches API errors before render

- [ ] **M4-CODE-02**: Scene-level code validation
  - AST check per scene before render
  - Structure check per scene
  - Manim API compatibility check

---

## Traceability

| Requirement | Phase | Success Criteria |
|-------------|-------|----------------|
| M4-STREAM-01 | Phase 13 | Scene < 30s generation |
| M4-STREAM-02 | Phase 13 | Parallel render overlap |
| M4-STREAM-03 | Phase 13 | Coherent narrative |
| M4-STREAM-04 | Phase 13 | Scene retry works |
| M4-CODE-01 | Phase 13 | No invalid APIs |
| M4-CODE-02 | Phase 13 | Pre-render validation |

---

*Requirements defined: 2026-04-05 for Milestone 4*
