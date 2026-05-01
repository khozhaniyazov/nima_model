# Research: Semantic RAG & Quality Prediction (Phase 6)

**Date:** 2026-04-05
**Phase:** 6 - Semantic RAG & Quality Prediction

---

## Current State

### RAG System (RAG_system.py)

**Current approach:** Keyword matching with scoring:
- +1 per keyword match
- +3 for domain match
- +5 for multi-word phrase match
- +2 per matching subtopic
- -2 penalty for tag overlap (diversity)

**Limitations:**
- No semantic understanding - "derivative" and "differentiate" don't match unless exact
- No vector embeddings
- No similarity scoring
- Corpus patterns are static (loaded from JSON)

### Quality Evaluation (ai_functions.py)

**Current approach:** `evaluate_with_gpt4()` scores after render:
- Scores: layout_quality, educational_value, technical_accuracy, pacing, manim_quality
- overall: 0-100
- Runs after successful render only

**Limitations:**
- No pre-render quality prediction
- Post-hoc evaluation only
- No way to predict render success before wasting render time

---

## Research: Semantic Embeddings for RAG

### Option 1: OpenAI Embeddings (Simple)

**Pros:**
- Easy to integrate (OpenAI SDK)
- High quality embeddings
- No model training required

**Cons:**
- API cost per query (~$0.0001 per 1K tokens)
- Latency (200-500ms per embedding lookup)
- Dependency on external API

### Option 2: Sentence Transformers (Local)

**Pros:**
- Free, runs locally
- Fast (GPU) or reasonable (CPU)
- No API dependency
- Good quality for code patterns

**Cons:**
- Need to host/manage model
- CPU inference slower
- Model selection needed

### Option 3: Hybrid (Recommended)

**Approach:**
- Use sentence-transformers for corpus embedding (offline, one-time)
- Cache embeddings in database
- Use simple cosine similarity at runtime
- Fallback to keyword matching if embeddings unavailable

**Architecture:**
```
Query → Embed(query) → CosineSimilarity(corpus_embeddings) → Top-k patterns
```

### Embedding Model Selection

**Recommended:** `sentence-transformers/all-MiniLM-L6-v2`
- 384 dimensions
- Fast (CPU)
- Good for code/math domains
- Apache licensed

---

## Research: Quality Prediction

### Pre-Render Quality Prediction

**Goal:** Predict if a render will succeed and be high-quality BEFORE running Manim.

**Approaches:**

1. **Code Analysis Model**
   - Analyze generated code before render
   - Check for common failure patterns
   - Predict success probability

2. **Historical Pattern Matching**
   - Find similar past prompts
   - Use their success rate as prediction
   - If similar prompt succeeded 90%+ of time, predict success

3. **LLM-based Prediction**
   - Ask GPT: "Will this code render successfully?"
   - Expensive but accurate
   - Use for high-value renders only

### Implementation Plan

**For M2-QUAL-01:** Pre-render quality prediction
- Use historical pattern matching first (low cost)
- Flag low-probability renders for review
- Don't block renders, just warn

---

## Research: High-Scorer Fine-Tuning

### Approach: Curated Fine-tuning Corpus

**Goal:** Fine-tune on high-scorers (≥80) to improve generation quality.

**Implementation options:**

1. **Periodic Fine-tuning (Recommended)**
   - Collect high-scorers monthly
   - Fine-tune a smaller model (GPT-4o-mini)
   - Use as secondary model for harder prompts

2. **Few-shot Prompting**
   - Inject high-scorer examples into prompt
   - No fine-tuning needed
   - Already doing this with RAG

3. **RAG + Fine-tuning Hybrid**
   - Use RAG for retrieval
   - Use fine-tuned model for generation
   - Best of both worlds

### For M2-RAG-02: High-scorer fine-tuning

**Decision:** Implement option 1 (periodic fine-tuning) as future work.
- Current RAG with high-scorers is sufficient for now
- Fine-tuning requires significant data (100+ high-scorers)
- Postpone until we have more data

---

## Error Pattern Learning

### Current State

Error patterns are recorded but not actively used to improve generation:
- `save_render_error()` records errors
- `get_error_patterns()` retrieves for avoidance
- No automatic categorization

### Improvements (M2-RAG-03)

1. **Auto-categorization**
   - Use LLM to categorize new errors
   - Add error_category field
   - Track root_cause automatically

2. **Active Avoidance**
   - Inject error patterns into generation prompt
   - Not just retrieval - proactive avoidance
   - "Common mistakes to avoid: ..."

---

## Summary: Phase 6 Tasks

| Requirement | Research Finding | Implementation |
|-------------|------------------|-----------------|
| M2-RAG-01 | Use sentence-transformers + cosine similarity | Add embedding pipeline to RAG |
| M2-RAG-02 | Periodic fine-tuning on high-scorers | Deferred - need more data |
| M2-RAG-03 | Auto-categorize + proactive avoidance | Enhance error_pattern injection |
| M2-QUAL-01 | Historical pattern matching | Pre-render prediction using past success |

---

## References

- Sentence Transformers: https://www.sbert.net/
- OpenAI Embeddings: https://platform.openai.com/docs/guides/embeddings
- Cosine Similarity: Standard vector math
