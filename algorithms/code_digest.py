from openai import OpenAI
import os
import re
import ast


from dotenv import load_dotenv
load_dotenv()

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))



def ensure_scene_class(code: str) -> str:
    if "class GeneratedScene(Scene)" in code:
        return code
    if "class " in code and "(Scene)" in code:
        code = re.sub(r'class\s+\w+\(Scene\)', 'class GeneratedScene(Scene)', code, count=1)
        return code
    indented_code = '\n'.join('        ' + line for line in code.split('\n') if line.strip())
    return f"""from manim import *

class GeneratedScene(Scene):
    def construct(self):
{indented_code}
"""

def validate_python_syntax(code: str) -> tuple[bool, str]:
    try:
        ast.parse(code)
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"Code parsing error: {str(e)}"

def validate_manim_code(code: str) -> tuple[bool, str]:
    checks = [
        ("from manim import", "Missing manim import"),
        ("class GeneratedScene(Scene)", "Missing GeneratedScene class"),
        ("def construct(self)", "Missing construct method"),
    ]
    
    for required, error_msg in checks:
        if required not in code:
            return False, error_msg
    return True, ""

def check_code_quality(code: str) -> tuple[bool, list]:
    print(f"[QUALITY] Running quality checks...")
    issues = []
    warnings = []
    
    wait_times = re.findall(r'self\.wait\((\d+\.?\d*)\)', code)
    if wait_times:
        total_wait = sum([float(w) for w in wait_times])
        if total_wait < 15:
            warnings.append(f" Total wait time only {total_wait}s")
    else:
        issues.append(" No wait() calls found")
    
    if code.count("self.play(FadeIn") > 10 and code.count("self.play(FadeOut") < 5:
        warnings.append(" Many FadeIn but few FadeOut")
    
    if "self.clear()" not in code and code.count("self.play(") > 15:
        warnings.append(" No self.clear() in long animation")
    
    # Check for abstract shapes in math
    if "Circle()" in code and ("math" in code.lower() or "homomorphism" in code.lower()):
        warnings.append(" Using abstract circles for math - use concrete examples")
    
    # Check for smart_text usage
    if "Text(" in code and "smart_text(" not in code:
        warnings.append(" Not using smart_text() - risk of overflow")
    
    print(f"[QUALITY] Warnings: {len(warnings)}, Issues: {len(issues)}")
    passes = len(issues) == 0
    return passes, issues + warnings