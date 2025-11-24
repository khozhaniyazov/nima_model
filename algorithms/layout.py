LAYOUT_HELPERS = """
# === AUTO-INJECTED LAYOUT SAFETY HELPERS ===
from manim import config

def smart_text(text_str, max_width=12, font_size=24):
    '''Auto-wrap and scale text to fit screen.'''
    t = Text(text_str, font_size=font_size)
    if t.width > max_width:
        t = t.scale_to_fit_width(max_width)
    return t

def fit_to_screen(mobject, margin=1):
    '''Scale any object to fit within screen bounds.'''
    target_width = config.frame_width - margin
    target_height = config.frame_height - margin
    if mobject.width > target_width:
        mobject.scale(target_width / mobject.width)
    if mobject.height > target_height:
        mobject.scale(target_height / mobject.height)
    return mobject

def safe_position(mobject, edge=UP, buff=0.5):
    '''Position object safely at screen edge.'''
    return mobject.to_edge(edge, buff=buff)

# === END HELPERS ===

"""

def inject_helpers(code: str) -> str:
    if "from manim import *" in code:
        return code.replace("from manim import *", 
                          "from manim import *\n" + LAYOUT_HELPERS)
    return LAYOUT_HELPERS + "\n" + code