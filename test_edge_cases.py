#!/usr/bin/env python3
"""
Edge-case stress test for NIMA streaming pipeline.

Tests diverse domains, edge cases, and tricky prompts that historically
break the pipeline. Each prompt targets a specific failure mode.

Usage:
  python test_edge_cases.py
  python test_edge_cases.py --count 5 --voiceover
  python test_edge_cases.py --pick 3   # random 3 from the pool
"""

from __future__ import annotations

import argparse
import random
from test_streaming_reliability import run_one, video_exists

# ═══════════════════════════════════════════════════════════════════════════════
# EDGE CASE PROMPT DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

EDGE_PROMPTS = {
    # ── MATH: calculus ────────────────────────────────────────────────────
    "calc_epsilon_delta": {
        "prompt": "Explain the epsilon-delta definition of a limit using f(x)=2x+1 at x=3.",
        "domain": "math",
        "edge": "Abstract concept with greek letters + visual proof",
    },
    "calc_improper_integral": {
        "prompt": "Show why the integral of 1/x^2 from 1 to infinity converges but 1/x diverges.",
        "domain": "math",
        "edge": "Infinity handling, comparison, two contrasting cases",
    },
    "calc_taylor_series": {
        "prompt": "Animate how Taylor polynomials of sin(x) get closer to the actual function as you add more terms.",
        "domain": "math",
        "edge": "Progressive animation, many curves overlaid",
    },
    # ── MATH: linear algebra ──────────────────────────────────────────────
    "linalg_svd": {
        "prompt": "Explain Singular Value Decomposition by showing how a 2x2 matrix transforms the unit circle into an ellipse.",
        "domain": "math",
        "edge": "Matrix decomposition, geometric transformation, multi-step",
    },
    "linalg_null_space": {
        "prompt": "Visualize the null space of [[1,2],[2,4]] by showing which vectors get mapped to zero.",
        "domain": "math",
        "edge": "Degenerate matrix, line in 2D, zero vector",
    },
    # ── MATH: discrete / combinatorics ────────────────────────────────────
    "discrete_pigeonhole": {
        "prompt": "Prove the pigeonhole principle using 6 socks in 5 drawers.",
        "domain": "math",
        "edge": "Proof by contradiction, physical analogy, discrete objects",
    },
    "discrete_bijection": {
        "prompt": "Explain bijection by showing a perfect pairing between {1,2,3} and {a,b,c}.",
        "domain": "math",
        "edge": "Set theory, arrows between elements, small finite sets",
    },
    # ── MATH: topology / analysis ─────────────────────────────────────────
    "topology_open_set": {
        "prompt": "Explain open sets vs closed sets on the real line using intervals (0,1) and [0,1].",
        "domain": "math",
        "edge": "Abstract topology concept, boundary points, open/closed dots",
    },
    # ── PHYSICS ───────────────────────────────────────────────────────────
    "physics_projectile": {
        "prompt": "Show projectile motion of a ball launched at 45 degrees, decomposing into horizontal and vertical components.",
        "domain": "physics",
        "edge": "2D motion, vectors, gravity, parabolic path",
    },
    "physics_wave_superposition": {
        "prompt": "Demonstrate wave superposition by adding two sine waves with different frequencies.",
        "domain": "physics",
        "edge": "Dynamic waves, interference patterns, ValueTracker",
    },
    "physics_electric_field": {
        "prompt": "Visualize the electric field lines between a positive and negative point charge.",
        "domain": "physics",
        "edge": "Vector field, field lines, dipole geometry",
    },
    # ── COMPUTER SCIENCE ──────────────────────────────────────────────────
    "cs_binary_search": {
        "prompt": "Animate binary search finding the number 7 in a sorted array [1,3,5,7,9,11,13].",
        "domain": "computer_science",
        "edge": "Array visualization, pointer movement, halving",
    },
    "cs_bfs_vs_dfs": {
        "prompt": "Compare BFS and DFS traversal on a binary tree side by side.",
        "domain": "computer_science",
        "edge": "Two simultaneous animations, tree structure, queue vs stack",
    },
    "cs_hash_collision": {
        "prompt": "Explain hash table collisions using chaining with 5 keys mapped to 3 buckets.",
        "domain": "computer_science",
        "edge": "Data structure, linked lists, collision resolution",
    },
    "cs_recursion_tree": {
        "prompt": "Show the recursion tree for fibonacci(5) and explain why it's exponential.",
        "domain": "computer_science",
        "edge": "Tree growth, duplicate subproblems, exponential blowup",
    },
    # ── CHEMISTRY ─────────────────────────────────────────────────────────
    "chem_electron_orbitals": {
        "prompt": "Visualize s, p, and d electron orbitals and how they differ in shape.",
        "domain": "chemistry",
        "edge": "3D-like shapes in 2D, orbital geometry, multiple objects",
    },
    "chem_reaction_rate": {
        "prompt": "Show how temperature affects reaction rate using the Arrhenius equation.",
        "domain": "chemistry",
        "edge": "Exponential curve, temperature slider, dynamic graph",
    },
    # ── TRICKY / EDGE CASES ───────────────────────────────────────────────
    "edge_very_short": {
        "prompt": "What is 2+2?",
        "domain": "math",
        "edge": "Extremely short prompt — should still produce valid animation",
    },
    "edge_long_formula": {
        "prompt": "Derive the quadratic formula from ax^2 + bx + c = 0 step by step, showing completing the square, isolating x, and arriving at x = (-b ± sqrt(b^2 - 4ac)) / 2a.",
        "domain": "math",
        "edge": "Long multi-step derivation, many LaTeX equations",
    },
    "edge_no_math": {
        "prompt": "Explain how a stack data structure works using a stack of plates analogy.",
        "domain": "computer_science",
        "edge": "Physical analogy, no equations, push/pop operations",
    },
    "edge_comparison": {
        "prompt": "Compare merge sort and quicksort by showing both sorting [5,3,8,1,9,2] simultaneously.",
        "domain": "computer_science",
        "edge": "Side-by-side animation, two algorithms, same input",
    },
    "edge_3d_concept": {
        "prompt": "Explain the gradient vector of f(x,y) = x^2 + y^2 and show it always points uphill.",
        "domain": "math",
        "edge": "3D concept forced into 2D, contour lines, vector field",
    },
    "edge_stats": {
        "prompt": "Explain the Central Limit Theorem by repeatedly sampling from a uniform distribution and plotting the means.",
        "domain": "math",
        "edge": "Statistical simulation, histogram animation, convergence",
    },
    "edge_game_theory": {
        "prompt": "Explain the Prisoner's Dilemma using a payoff matrix and show Nash equilibrium.",
        "domain": "math",
        "edge": "Game theory, matrix, strategic reasoning, non-standard domain",
    },
}


def main() -> int:
    ap = argparse.ArgumentParser(description="Edge-case stress test")
    ap.add_argument("--host", default="http://localhost:5000")
    ap.add_argument("--count", type=int, default=5, help="Number of prompts to run")
    ap.add_argument("--timeout", type=int, default=1200, help="Per-job timeout")
    ap.add_argument("--poll", type=float, default=2.0)
    ap.add_argument("--voiceover", action="store_true")
    ap.add_argument("--pick", type=int, default=0, help="Random pick N from pool")
    ap.add_argument("--domain", default=None, help="Filter by domain")
    ap.add_argument("--list", action="store_true", help="List all prompts and exit")
    args = ap.parse_args()

    # List mode
    if args.list:
        for key, val in EDGE_PROMPTS.items():
            print(f"  {key:30s} [{val['domain']:20s}] {val['edge']}")
        print(f"\n{len(EDGE_PROMPTS)} prompts available")
        return 0

    # Build prompt list
    pool = list(EDGE_PROMPTS.items())
    if args.domain:
        pool = [(k, v) for k, v in pool if v["domain"] == args.domain]

    random.shuffle(pool)
    if args.pick > 0:
        pool = pool[: min(args.pick, len(pool))]
    else:
        pool = pool[: min(args.count, len(pool))]

    print("NIMA Edge-Case Stress Test")
    print(f"Host: {args.host}")
    print(f"Jobs: {len(pool)}")
    print(f"Voiceover: {args.voiceover}")
    print("-" * 72)

    results = []
    for i, (key, spec) in enumerate(pool):
        prompt = spec["prompt"]
        print(f"\n[{i + 1}/{len(pool)}] [{spec['domain']}] {key}")
        print(f"  prompt: {prompt}")
        print(f"  edge:   {spec['edge']}")

        try:
            res = run_one(args.host, prompt, args.timeout, args.poll, args.voiceover)
        except Exception as e:
            res = {
                "job_id": None,
                "status": "error",
                "message": f"Unhandled: {e}",
                "elapsed": 0.0,
                "video_file": "",
                "video_exists": False,
                "repetition_pairs": [],
                "max_repetition": 0.0,
            }

        res["key"] = key
        res["domain"] = spec["domain"]
        res["edge"] = spec["edge"]
        results.append(res)

        success = res["status"] == "done" and res["video_exists"]
        icon = "✓" if success else "✗"
        print(
            f"  {icon} status={res['status']} job={res.get('job_id')} "
            f"time={res['elapsed']:.1f}s exists={res['video_exists']} "
            f"repeat={res.get('max_repetition', 0.0):.3f}"
        )
        if not success and res.get("message"):
            print(f"    error: {res['message']}")

    # ── Summary ───────────────────────────────────────────────────────────
    ok = [r for r in results if r["status"] == "done" and r["video_exists"]]
    fail = [r for r in results if r not in ok]
    repeat_flag = [r for r in results if r.get("max_repetition", 0.0) >= 0.75]
    avg = sum(r["elapsed"] for r in ok) / len(ok) if ok else 0.0

    print("\n" + "=" * 72)
    print("EDGE-CASE RESULTS")
    print(f"Success:    {len(ok)}/{len(results)}")
    print(f"Failure:    {len(fail)}/{len(results)}")
    print(f"Avg time:   {avg:.1f}s")
    print(f"Repeats:    {len(repeat_flag)}")

    if fail:
        print("\nFailed prompts:")
        for r in fail:
            print(f"  ✗ {r['key']:30s} [{r['domain']}] {r.get('message', '')[:60]}")

    if ok:
        print("\nSuccessful prompts:")
        for r in ok:
            print(f"  ✓ {r['key']:30s} [{r['domain']}] {r['elapsed']:.0f}s")

    # ── Domain breakdown ──────────────────────────────────────────────────
    domains = {}
    for r in results:
        d = r.get("domain", "unknown")
        if d not in domains:
            domains[d] = {"ok": 0, "fail": 0}
        if r in ok:
            domains[d]["ok"] += 1
        else:
            domains[d]["fail"] += 1

    print("\nDomain breakdown:")
    for d, counts in sorted(domains.items()):
        total = counts["ok"] + counts["fail"]
        print(f"  {d:20s} {counts['ok']}/{total}")

    return 0 if (len(ok) == len(results) and len(repeat_flag) == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
