GOLDEN_PATTERNS = {
    "math_function_graph": """
# PROVEN PATTERN: Function Graphing
axes = Axes(
    x_range=[-5, 5, 1],
    y_range=[-5, 5, 1],
    x_length=10,
    y_length=6,
).add_coordinates()

# Plot function
graph = axes.plot(lambda x: x**2, color=BLUE)
label = axes.get_graph_label(graph, label='f(x)=x^2').scale(0.7)

self.play(Create(axes), run_time=1.5)
self.play(Create(graph), Write(label), run_time=2)
self.wait(2)
""",
    
    "math_group_operation": """
# PROVEN PATTERN: Group Operations
elements = VGroup(*[
    Text(str(i), font_size=36) for i in range(4)
]).arrange(RIGHT, buff=0.8)

operation_label = Text("Group Operation: +", font_size=28).to_edge(UP)

# Show specific operation
elem1 = elements[2].copy().set_color(YELLOW)
elem2 = elements[3].copy().set_color(YELLOW)
result_text = Text("Result: 1", font_size=36, color=GREEN)

self.add(operation_label)
self.play(Create(elements))
self.play(Indicate(elem1), Indicate(elem2))
self.play(Write(result_text))
self.wait(2)
""",
    
    "stepbystep_calculation": """
# PROVEN PATTERN: Step-by-Step Math
steps = VGroup(
    Text("Step 1: Given equation", font_size=28),
    Text("Step 2: Simplify left side", font_size=28),
    Text("Step 3: Simplify right side", font_size=28),
    Text("Step 4: Compare results", font_size=28),
    Text("Conclusion: Property verified!", font_size=32, color=GREEN)
).arrange(DOWN, aligned_edge=LEFT, buff=0.4)

for i, step in enumerate(steps):
    self.play(Write(step), run_time=1)
    self.wait(1.5)
    if i < len(steps) - 1:
        self.play(Indicate(step))
self.wait(2)
"""
}

def retrieve_golden_example(domain: str, topic: str, db: ManimDatabase = None) -> str:
    
    pattern_key = f"{domain}_{topic.lower().replace(' ', '_')}"
    if pattern_key in GOLDEN_PATTERNS:
        return GOLDEN_PATTERNS[pattern_key]
    if domain == 'math':
        return GOLDEN_PATTERNS.get('math_function_graph', '')
    
    if db:
        examples = db.get_best_examples(domain=domain, limit=1)
        if examples:
            return f"# Example from database (score: {examples[0]['overall_score']})\n{examples[0]['final_code'][:500]}"
    
    return ""