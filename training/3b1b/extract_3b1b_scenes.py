import os
import re
import json

ROOT = "videos"
OUTPUT = []

scene_pattern = re.compile(
    r"class\s+(\w+)\((?:ThreeDScene|Scene|LinearTransformationScene).*?\):(.*?)(?=\nclass|\Z)",
    re.S
)

for root, dirs, files in os.walk(ROOT):

    for file in files:

        if not file.endswith(".py"):
            continue

        path = os.path.join(root, file)

        with open(path, "r", encoding="utf8", errors="ignore") as f:
            code = f.read()

        scenes = scene_pattern.findall(code)

        for name, body in scenes:

            OUTPUT.append({
                "scene": name,
                "file": file,
                "path": path,
                "code": body.strip()
            })

print("Scenes found:", len(OUTPUT))

with open("3b1b_scenes.json","w") as f:
    json.dump(OUTPUT, f, indent=2)