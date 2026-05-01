# Research: Template Expansion (Phase 7)

**Date:** 2026-04-05
**Phase:** 7 - Template Expansion

---

## Current State

### Template Registry (template_registry.py)

**Existing templates by domain:**

**Math (9 templates):**
- two_panel_comparison
- definition_to_example
- step_by_step_derivation
- graph_and_formula
- mapping_diagram
- derivative_exploration
- sequence_convergence
- matrix_transform
- area_under_curve
- step_by_step_proof

**Physics (0 templates):** Needs expansion
**CS (0 templates):** Needs expansion
**Chemistry (0 templates):** Needs expansion

### Domain Guidance (ai_functions.py)

**Physics guidance exists but no templates:**
- ArrowVectorField
- StreamLines
- Pendulum oscillation
- Wave superposition

**CS guidance exists but no templates:**
- Array sorting (bubble sort pattern)
- Binary tree traversal
- Linked list

**Chemistry guidance exists but no templates:**
- Water molecule pattern
- Reaction mechanism pattern
- Electron shell pattern

---

## Requirements Analysis

### M2-TEMP-01: Physics Templates

**Wave Propagation Template:**
- Visualize sound waves, light waves, water waves
- Key animations: sine wave animation, wavelength, amplitude, superposition
- Manim objects: Axes, Graph, ValueTracker for phase

**Field Visualization Template:**
- Electric/magnetic field lines
- Gradient fields
- Key animations: ArrowVectorField, StreamLines
- Manim objects: ArrowVectorField, StreamLines

**Oscillation Template:**
- Pendulum, spring-mass system, LC circuits
- Key animations: periodic motion with ValueTracker
- Manim objects: ValueTracker, always_redraw, Circle, Line

### M2-TEMP-02: CS Templates

**Sorting Algorithm Template:**
- Bubble sort, selection sort, insertion sort
- Key animations: comparison highlight, swap animation, sorted region
- Manim objects: VGroup of Rectangle+Text, color transitions

**Tree Traversal Template:**
- Binary tree, BST operations
- Key animations: node highlight, traversal path, recursive calls
- Manim objects: Circle nodes, Line edges, Indicate

**Graph Algorithm Template:**
- BFS, DFS, Dijkstra visualization
- Key animations: visited set, frontier, shortest path
- Manim objects: Dot nodes, Line edges, color changes

### M2-TEMP-03: Chemistry Templates

**Reaction Mechanism Template:**
- Reactants → products with electron movement
- Key animations: bond breaking, bond forming, electron arrow
- Manim objects: Dot (atoms), Line (bonds), CurvedArrow (electrons)

**Orbital Visualization Template:**
- Electron shells, orbital shapes
- Key animations: electron placement, shell filling
- Manim objects: Circle shells, Dot electrons

**Molecule Building Template:**
- 3D representation of molecules
- Key animations: atom placement, bond formation
- Manim objects: Dot atoms, Line bonds, VGroup

### M2-TEMP-04: User Template Contribution

**Requirements:**
- Users can submit custom templates
- Templates stored in database or filesystem
- Admin review/approval workflow
- Template tagging and search

**Architecture:**
- New `/api/templates` endpoint
- Template schema: name, domain, slots, beats, notes, code_pattern
- User submission form (frontend)
- Admin approval view

---

## Template Slots Design

### Template Structure

Each template has:
```python
{
    "name": "Template Name",
    "slots": ["slot1", "slot2", ...],  # LLM fills these
    "beats": 5,  # Number of animation beats
    "palette": ["#color1", "#color2"],  # Optional color scheme
    "notes": "Layout instructions for LLM"
}
```

### New Slots Needed

**Physics Slots:**
- `wave_type`: "sine" | "cosine" | "square"
- `amplitude`, `wavelength`, `frequency`
- `field_type`: "electric" | "magnetic" | "gravitational"
- `oscillation_type`: "pendulum" | "spring" | "lc_circuit"

**CS Slots:**
- `algorithm_name`: "bubble_sort" | "quick_sort" | "merge_sort"
- `data_structure`: "array" | "tree" | "graph" | "linked_list"
- `traversal_type`: "bfs" | "dfs" | "inorder" | "preorder" | "postorder"

**Chemistry Slots:**
- `reaction_type`: "synthesis" | "decomposition" | "substitution" | "combustion"
- `molecule_name`: chemical formula
- `orbital_type`: "s" | "p" | "d" | "f"

---

## Implementation Plan

### Phase 7 Tasks

1. **Add Physics Templates (M2-TEMP-01)**
   - wave_propagation
   - field_visualization
   - oscillation_motion

2. **Add CS Templates (M2-TEMP-02)**
   - sorting_algorithm
   - tree_traversal
   - graph_traversal

3. **Add Chemistry Templates (M2-TEMP-03)**
   - reaction_mechanism
   - orbital_visualization
   - molecule_building

4. **Add User Template System (M2-TEMP-04)**
   - Database table for user templates
   - API endpoints for CRUD
   - Frontend contribution form
   - Admin approval flow

---

## Summary

| Requirement | Templates to Add | Priority |
|-------------|------------------|----------|
| M2-TEMP-01 | wave_propagation, field_visualization, oscillation_motion | High |
| M2-TEMP-02 | sorting_algorithm, tree_traversal, graph_traversal | High |
| M2-TEMP-03 | reaction_mechanism, orbital_visualization, molecule_building | High |
| M2-TEMP-04 | User template API, frontend, admin approval | Medium |
