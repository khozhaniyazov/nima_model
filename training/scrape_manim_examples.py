import requests
from bs4 import BeautifulSoup
import json
import re

URL = "https://docs.manim.community/en/stable/examples.html"

print("Downloading page...")

html = requests.get(URL).text
soup = BeautifulSoup(html, "html.parser")

examples = []

# Find all python code blocks
blocks = soup.select("div.highlight-python pre")

print("Code blocks found:", len(blocks))

scene_pattern = re.compile(
    r"class\s+(\w+)\((?:Scene|ThreeDScene|MovingCameraScene).*?\):(.*)",
    re.S
)

for block in blocks:

    code = block.get_text()

    match = scene_pattern.search(code)

    if not match:
        continue

    scene_name = match.group(1)

    examples.append({
        "scene": scene_name,
        "code": code.strip()
    })

print("Scenes extracted:", len(examples))

with open("manim_examples_raw.json", "w", encoding="utf8") as f:
    json.dump(examples, f, indent=2)

print("Saved to manim_examples_raw.json")