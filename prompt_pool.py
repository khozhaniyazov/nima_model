#!/usr/bin/env python3
"""Shared prompt pool for long-run reliability and edge-case testing."""

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
    "topology_open_set": {
        "prompt": "Explain open sets vs closed sets on the real line using intervals (0,1) and [0,1].",
        "domain": "math",
        "edge": "Abstract topology concept, boundary points, open/closed dots",
    },
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
    "analysis_uniform_conv": {
        "prompt": "Explain uniform convergence by comparing pointwise convergence and uniform convergence on a sequence of functions.",
        "domain": "math",
        "edge": "Abstract analysis, compare two convergence modes visually",
    },
    "analysis_compactness": {
        "prompt": "Explain compactness on the real line using open covers of a closed interval.",
        "domain": "math",
        "edge": "Highly abstract topology/analysis concept",
    },
    "prob_bayes": {
        "prompt": "Explain Bayes' theorem using a medical test example with false positives.",
        "domain": "math",
        "edge": "Conditional probability, tree/table visualization",
    },
    "prob_random_walk": {
        "prompt": "Visualize a one-dimensional random walk and explain expected drift over many trials.",
        "domain": "math",
        "edge": "Stochastic process, repeated simulation feel",
    },
    "number_group_mod": {
        "prompt": "Explain arithmetic modulo 5 by showing addition on a clock face.",
        "domain": "math",
        "edge": "Cyclic structure, modular arithmetic, non-linear layout",
    },
    "number_prime_factor": {
        "prompt": "Explain the Fundamental Theorem of Arithmetic by factoring 60 and 84 into primes.",
        "domain": "math",
        "edge": "Factor trees, uniqueness of factorization",
    },
    "linalg_rank_nullity": {
        "prompt": "Explain the rank-nullity theorem using a 3x2 matrix that collapses one direction.",
        "domain": "math",
        "edge": "Linear algebra theorem + geometry",
    },
    "linalg_orthogonality": {
        "prompt": "Explain orthogonality using dot products of (1,0) and (0,1).",
        "domain": "math",
        "edge": "Simple vectors but conceptually foundational",
    },
    "cs_dijkstra": {
        "prompt": "Explain Dijkstra's algorithm on a weighted graph and show how shortest paths are updated.",
        "domain": "computer_science",
        "edge": "Weighted graph, repeated relaxation, path updates",
    },
    "cs_dynamic_programming": {
        "prompt": "Explain dynamic programming using the coin change problem with coins 1, 3, and 4.",
        "domain": "computer_science",
        "edge": "Table filling, recursion vs memoization",
    },
    "cs_union_find": {
        "prompt": "Explain union-find with path compression using connectivity among 6 nodes.",
        "domain": "computer_science",
        "edge": "Forest structure, repeated updates, pointer rewiring",
    },
    "cs_state_machine": {
        "prompt": "Explain a finite state machine using a turnstile that locks and unlocks.",
        "domain": "computer_science",
        "edge": "States/transitions, practical automata example",
    },
    "cs_heap": {
        "prompt": "Show how a max-heap inserts the values 7, 3, 10, 1, 8 while preserving heap order.",
        "domain": "computer_science",
        "edge": "Tree + swaps + heap invariant",
    },
    "physics_shm": {
        "prompt": "Explain simple harmonic motion using a mass on a spring and compare position, velocity, and acceleration.",
        "domain": "physics",
        "edge": "Multi-graph synchronization, oscillation",
    },
    "physics_momentum": {
        "prompt": "Explain conservation of momentum using a collision between two carts on a track.",
        "domain": "physics",
        "edge": "Before/after comparison, vectors, collision event",
    },
    "physics_energy_landscape": {
        "prompt": "Show potential and kinetic energy exchange for a pendulum swinging from side to side.",
        "domain": "physics",
        "edge": "Coupled animations, energy bars, periodic motion",
    },
    "chem_ph_curve": {
        "prompt": "Explain a titration curve and show equivalence point for a strong acid and strong base.",
        "domain": "chemistry",
        "edge": "Curve interpretation, chemistry-specific labels",
    },
    "chem_equilibrium": {
        "prompt": "Explain Le Chatelier's principle using a reversible reaction disturbed by concentration change.",
        "domain": "chemistry",
        "edge": "Dynamic equilibrium, left-right shift metaphor",
    },
    "chem_orbital_hybrid": {
        "prompt": "Explain sp, sp2, and sp3 hybridization using bond geometry diagrams.",
        "domain": "chemistry",
        "edge": "Spatial geometry, chemistry notation",
    },
    "econ_supply_demand": {
        "prompt": "Explain supply and demand using two curves and show what happens when demand shifts right.",
        "domain": "general",
        "edge": "Economics graph, comparative statics",
    },
    "game_zero_sum": {
        "prompt": "Explain zero-sum games using rock-paper-scissors and a payoff matrix.",
        "domain": "general",
        "edge": "Game theory but not pure linear algebra",
    },
    "logic_truth_table": {
        "prompt": "Explain implication and equivalence using a truth table for propositions p and q.",
        "domain": "math",
        "edge": "Logic symbols, table layout, abstract semantics",
    },
    "stats_regression": {
        "prompt": "Explain linear regression by fitting a line through noisy data points and interpreting slope.",
        "domain": "math",
        "edge": "Scatter plot, best-fit line, statistical interpretation",
    },
    "calc_series_geometric": {
        "prompt": "Explain an infinite geometric series using repeatedly halving a segment and summing the pieces.",
        "domain": "math",
        "edge": "Convergence + visual accumulation",
    },
    "graph_markov": {
        "prompt": "Explain a transition matrix using a 4-state weather Markov chain.",
        "domain": "math",
        "edge": "State graph + matrix + probabilities",
    },
    "proof_induction": {
        "prompt": "Prove by induction that 1 + 2 + ... + n = n(n+1)/2.",
        "domain": "math",
        "edge": "Formal proof structure with base case and inductive step",
    },
    "abstract_metric_space": {
        "prompt": "Explain what a metric space is using the real line and Euclidean distance as the first example.",
        "domain": "math",
        "edge": "Abstract definition grounded in familiar example",
    },
    "cs_trie": {
        "prompt": "Explain a trie by storing the words cat, car, dog, and dot.",
        "domain": "computer_science",
        "edge": "Prefix tree, branching text structure",
    },
    "cs_kmp": {
        "prompt": "Explain KMP string matching using pattern ABABC and text ABABABCAB.",
        "domain": "computer_science",
        "edge": "Pattern matching, prefix table, index movement",
    },
    "physics_entropy": {
        "prompt": "Explain entropy using gas particles spreading from one side of a box to the whole container.",
        "domain": "physics",
        "edge": "Many-particle metaphor, disorder, probability",
    },
    "chem_mole_concept": {
        "prompt": "Explain the mole concept by comparing a dozen eggs to Avogadro's number of particles.",
        "domain": "chemistry",
        "edge": "Huge-number analogy, chemistry foundation",
    },
}


COURSE_PROMPTS = {
    "course_limits": {
        "prompt": "Teach the idea of limits from intuitive approach to one-sided limits, infinite limits, and the epsilon-delta definition, using several concrete function examples.",
        "domain": "math",
        "edge": "broad calculus topic, multi-stage lesson",
    },
    "course_derivatives": {
        "prompt": "Teach derivatives as rates of change, tangent slopes, derivative rules, chain rule, and applications to motion and optimization in one coherent lesson.",
        "domain": "math",
        "edge": "broad calculus topic, multiple subtopics",
    },
    "course_integrals": {
        "prompt": "Teach definite and indefinite integrals, area accumulation, Fundamental Theorem of Calculus, and simple applications in one continuous explainer.",
        "domain": "math",
        "edge": "broad calculus topic, many visual transitions",
    },
    "course_series": {
        "prompt": "Teach infinite series, geometric series, p-series, convergence vs divergence, and Taylor series intuition as one lecture-length visual explanation.",
        "domain": "math",
        "edge": "long analysis topic with many related subparts",
    },
    "course_linear_algebra": {
        "prompt": "Teach matrices as linear transformations, determinants, eigenvalues, eigenvectors, and change of basis in one visually connected lesson.",
        "domain": "math",
        "edge": "broad linear algebra topic, geometry-heavy",
    },
    "course_vector_spaces": {
        "prompt": "Teach vector spaces, subspaces, span, linear independence, basis, and dimension using concrete geometric examples throughout.",
        "domain": "math",
        "edge": "abstract algebraic structures with geometry grounding",
    },
    "course_probability": {
        "prompt": "Teach probability from sample spaces and events through conditional probability, Bayes theorem, random variables, expectation, and common distributions.",
        "domain": "math",
        "edge": "broad probability curriculum",
    },
    "course_statistics": {
        "prompt": "Teach mean, variance, sampling distributions, confidence intervals, regression, and the Central Limit Theorem in one connected statistics lesson.",
        "domain": "math",
        "edge": "broad statistics curriculum",
    },
    "course_graph_theory": {
        "prompt": "Teach graphs, paths, cycles, adjacency matrices, connectivity, traversals, and Eulerian vs Hamiltonian ideas in one graph theory lecture.",
        "domain": "math",
        "edge": "many graph subtopics, mixed visuals",
    },
    "course_discrete_math": {
        "prompt": "Teach sets, relations, functions, induction, the pigeonhole principle, and counting arguments in one discrete mathematics lesson.",
        "domain": "math",
        "edge": "broad proof-heavy topic",
    },
    "course_real_analysis": {
        "prompt": "Teach sequences, continuity, uniform continuity, compactness, open and closed sets, and convergence ideas in one real analysis overview.",
        "domain": "math",
        "edge": "abstract long-form topic",
    },
    "course_diff_eq": {
        "prompt": "Teach first-order differential equations, separable equations, integrating factors, and why Laplace transforms help solve them.",
        "domain": "math",
        "edge": "multi-technique differential equations lesson",
    },
    "course_group_theory": {
        "prompt": "Teach groups, subgroups, cyclic groups, cosets, and homomorphisms using integers, modular arithmetic, and symmetry examples.",
        "domain": "math",
        "edge": "abstract algebra lesson with concrete anchors",
    },
    "course_algorithms": {
        "prompt": "Teach algorithmic thinking through sorting, searching, divide-and-conquer, graph algorithms, and dynamic programming in one lecture-style overview.",
        "domain": "computer_science",
        "edge": "broad CS course topic",
    },
    "course_data_structures": {
        "prompt": "Teach arrays, linked lists, stacks, queues, trees, heaps, hash tables, and tries in one visual data structures lesson.",
        "domain": "computer_science",
        "edge": "many structural transitions",
    },
    "course_automata": {
        "prompt": "Teach finite state machines, regular languages, transition diagrams, and why automata matter in computing.",
        "domain": "computer_science",
        "edge": "theory-heavy CS topic",
    },
    "course_graph_algorithms": {
        "prompt": "Teach BFS, DFS, shortest paths, spanning trees, and graph representations as one connected graph algorithms lesson.",
        "domain": "computer_science",
        "edge": "broad graph algorithm topic",
    },
    "course_complexity": {
        "prompt": "Teach time complexity, Big-O notation, recursion trees, logarithmic vs linear vs quadratic growth, and why complexity matters.",
        "domain": "computer_science",
        "edge": "abstract performance topic",
    },
    "course_mechanics": {
        "prompt": "Teach motion, velocity, acceleration, forces, momentum, and energy conservation as one introductory mechanics lesson.",
        "domain": "physics",
        "edge": "broad physics curriculum topic",
    },
    "course_waves": {
        "prompt": "Teach oscillations, simple harmonic motion, waves, interference, resonance, and energy transfer in one coherent physics lesson.",
        "domain": "physics",
        "edge": "multiple dynamic wave visuals",
    },
    "course_electricity": {
        "prompt": "Teach electric charge, electric fields, potential, current, and simple circuits in one conceptual introduction.",
        "domain": "physics",
        "edge": "field visuals + circuit ideas",
    },
    "course_thermo": {
        "prompt": "Teach temperature, heat, entropy, probability, and the second law of thermodynamics as one visual introduction.",
        "domain": "physics",
        "edge": "bridges microscopic and macroscopic explanations",
    },
    "course_quantum_intro": {
        "prompt": "Teach wavefunctions, probability amplitudes, energy levels, and orbitals as a gentle introduction to quantum mechanics.",
        "domain": "physics",
        "edge": "abstract quantum topic",
    },
    "course_chem_bonding": {
        "prompt": "Teach atomic structure, orbitals, bonding, hybridization, and molecular geometry in one chemistry lesson.",
        "domain": "chemistry",
        "edge": "broad chemistry foundations topic",
    },
    "course_chem_equilibrium": {
        "prompt": "Teach reaction rates, equilibrium, Le Chatelier's principle, and activation energy in one connected chemistry lesson.",
        "domain": "chemistry",
        "edge": "dynamic chemistry topic",
    },
    "course_chem_acid_base": {
        "prompt": "Teach acids and bases, pH, titration curves, and buffers in one introductory chemistry lesson.",
        "domain": "chemistry",
        "edge": "curve + conceptual chemistry topic",
    },
    "course_microeconomics": {
        "prompt": "Teach supply and demand, equilibrium, elasticity, incentives, and strategic interaction in one microeconomics lesson.",
        "domain": "general",
        "edge": "broad economics topic with graphs and matrices",
    },
    "course_game_theory": {
        "prompt": "Teach strategic interaction through payoff matrices, dominant strategies, Nash equilibrium, zero-sum games, and the Prisoner's Dilemma.",
        "domain": "general",
        "edge": "broad game theory lesson",
    },
    "course_logic_proofs": {
        "prompt": "Teach logical implication, equivalence, contradiction, induction, and proof strategies in one foundations-of-math lesson.",
        "domain": "math",
        "edge": "broad proof and logic topic",
    },
    "course_markov_models": {
        "prompt": "Teach stochastic processes through Markov chains, transition matrices, stationary behavior, and simple state models.",
        "domain": "math",
        "edge": "long-form probability + matrix topic",
    },
}


LONG_RUN_PROMPTS = {**EDGE_PROMPTS, **COURSE_PROMPTS}
