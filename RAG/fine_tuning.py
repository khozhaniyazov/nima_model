"""
Fine-tuning infrastructure for NIMA (M2-RAG-02).

This module prepares high-scorer examples for model fine-tuning.

PREREQUISITES FOR FINE-TUNING:
- Minimum 100 high-scorer examples (score >= 80)
- Diverse coverage across domains (math, physics, CS, chemistry)
- OpenAI API access for fine-tuning

CURRENT STATUS: Placeholder - full implementation deferred
until sufficient high-scorer examples are collected.
"""

from __future__ import annotations
from typing import List, Dict, Optional


def prepare_finetune_dataset(
    db=None, min_score: int = 80, limit: int = 100
) -> List[Dict]:
    """
    Prepare high-scorer examples for fine-tuning dataset.

    Requires:
    - db: Database connection for retrieving high-scorers
    - min_score: Minimum quality score threshold (default: 80)
    - limit: Maximum number of examples to include

    Returns:
    - List of dicts with 'prompt' and 'completion' keys
      suitable for OpenAI fine-tuning format.

    Current implementation: Returns empty list.
    Full implementation pending 100+ high-scorers.
    """
    if not db or not db.available:
        print("[FINETUNE] Database not available - cannot prepare dataset")
        return []

    try:
        examples = db.get_best_examples(domain=None, limit=limit * 2)
        high_scorers = [e for e in examples if e.get("overall_score", 0) >= min_score]

        if len(high_scorers) < 100:
            print(
                f"[FINETUNE] Only {len(high_scorers)} high-scorers found. Need 100+ for effective fine-tuning."
            )
            print(f"[FINETUNE] Collected: {len(high_scorers)}, Required: 100")
            return []

        dataset = []
        for ex in high_scorers[:limit]:
            dataset.append(
                {
                    "prompt": ex.get("prompt", ""),
                    "completion": ex.get("final_code", "")[:1500],
                }
            )

        print(f"[FINETUNE] Prepared {len(dataset)} examples for fine-tuning")
        return dataset

    except Exception as e:
        print(f"[FINETUNE] Error preparing dataset: {e}")
        return []


def trigger_finetune(
    training_data_path: str = None, model_name: str = "gpt-4o-mini"
) -> Optional[str]:
    """
    Trigger a fine-tuning job on OpenAI.

    Args:
        training_data_path: Path to JSONL file with training data
        model_name: Base model to fine-tune

    Returns:
        Fine-tune job ID if successful, None otherwise.

    NOTE: This is a placeholder. Full implementation requires:
    - Preparing training data with prepare_finetune_dataset()
    - Uploading to OpenAI via openai.File.create()
    - Creating fine-tune job via openai.FineTuningJob.create()
    - Monitoring job status and retrieving final model ID
    """
    print("[FINETUNE] Placeholder - full implementation deferred")
    print(f"[FINETUNE] Would trigger fine-tune on {model_name}")
    print("[FINETUNE] Prerequisites:")
    print("[FINETUNE]   1. Collect 100+ high-scorers (score >= 80)")
    print("[FINETUNE]   2. Prepare dataset with prepare_finetune_dataset()")
    print(
        "[FINETUNE]   3. Upload to OpenAI: openai.File.create(file=..., purpose='fine-tune')"
    )
    print(
        "[FINETUNE]   4. Create job: openai.FineTuningJob.create(training_file=..., model=...)"
    )
    return None


def check_finetune_status(job_id: str) -> Dict:
    """
    Check the status of a fine-tuning job.

    Returns dict with:
    - status: 'pending', 'running', 'succeeded', 'failed'
    - model: fine-tuned model ID if succeeded
    - error: error message if failed

    NOTE: Placeholder implementation.
    """
    print(f"[FINETUNE] Placeholder - would check status of job {job_id}")
    return {
        "status": "pending",
        "job_id": job_id,
        "error": "Placeholder - implement when fine-tuning is ready",
    }


def flag_for_finetune(
    db=None, code: str = None, prompt: str = None, score: int = None, domain: str = None
) -> bool:
    """
    Flag a high-quality example for future fine-tuning.

    When a render achieves a high score (>= 85), this function
    stores it in a separate table for later fine-tuning corpus.

    Args:
        db: Database connection
        code: Generated Manim code
        prompt: Original prompt
        score: Quality score
        domain: Animation domain

    Returns:
        True if flagged successfully, False otherwise.
    """
    if not db or not db.available:
        return False

    if not code or not prompt or score is None:
        return False

    if score < 85:
        return False

    try:
        db._exec(
            """INSERT INTO fine_tune_candidates
               (prompt, code, score, domain, created_at)
               VALUES (%s, %s, %s, %s, NOW())
               ON CONFLICT DO NOTHING""",
            (prompt, code[:5000], score, domain),
        )
        print(f"[FINETUNE] Flagged high-scorer ({score}) for future fine-tuning")
        return True
    except Exception as e:
        print(f"[FINETUNE] Error flagging for fine-tune: {e}")
        return False
