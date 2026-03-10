# Fast Pipeline Proposal (Reduce LLM Calls + Render Time)

## Goals
- Reduce LLM calls per job from 4–6 to 1–2.
- Avoid repeated re-prompts for minor fixes.
- Keep math prompts deterministic and template-driven.
- Preserve quality while dramatically cutting latency.

## Proposed Pipeline Changes
1) **Single-pass generation**
   - One LLM call to produce the final Manim code.
   - Remove the separate "quality" and "eval" passes by default.

2) **Deterministic plan for math**
   - Use the template compiler for math prompts (no LLM plan step).
   - One LLM call to fill content into the chosen template.

3) **Rule-based checks first**
   - Run overlap detector + syntax checks.
   - Only call LLM for a single repair pass if the code fails.

4) **No iterative retries by default**
   - Set `MAX_GENERATION_ATTEMPTS=1`.
   - Set `MAX_RENDER_RETRIES=1`.

5) **Remove automatic "polish" stage**
   - Keep available, but off by default.

## Config Flag
Introduce `FAST_PIPELINE=true` to:
- Skip review/eval.
- Force deterministic planning for math prompts.
- Limit retries to 1.
- Allow only a single repair pass if render fails.

## Expected Impact
- LLM calls per job: 1–2
- Faster overall wall time.
- Fewer render retries and less churn.

## Next Steps
- Implement the `FAST_PIPELINE` flag.
- Update `app.py` flow to bypass eval/review when enabled.
- Update `algorithms/request_analysis.py` to skip narrative plan steps in fast mode.
- Add logging so we can compare latency with and without `FAST_PIPELINE`.
