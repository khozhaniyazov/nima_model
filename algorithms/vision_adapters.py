"""Optional local vision/OCR adapters.

No OCR dependency is required. If a local backend is installed or configured,
these helpers can enrich frame-quality reports; otherwise they return a disabled
report and the render pipeline continues normally.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shlex
import subprocess
import statistics
from pathlib import Path
from typing import Iterable

_EASYOCR_READER = None
_PADDLE_OCR = None


def _empty_ocr_result(enabled: bool, backend: str | None, error: str = "") -> dict:
    return {
        "enabled": enabled,
        "backend": backend,
        "text": "",
        "boxes": [],
        "text_boxes": 0,
        "overlap_ratio": 0.0,
        "edge_clip_ratio": 0.0,
        "mean_confidence": 0.0,
        "error": error,
    }


def available_ocr_backends() -> list[str]:
    """Return OCR backends that appear importable/configured locally."""
    backends = []
    if os.getenv("NIMA_OCR_COMMAND"):
        backends.append("command")
    for module, label in (
        ("pytesseract", "pytesseract"),
        ("easyocr", "easyocr"),
        ("paddleocr", "paddleocr"),
    ):
        if importlib.util.find_spec(module):
            backends.append(label)
    return backends


def _box_area(box: dict) -> int:
    return max(0, int(box["x2"]) - int(box["x1"])) * max(
        0, int(box["y2"]) - int(box["y1"])
    )


def _box_intersection(a: dict, b: dict) -> int:
    x1 = max(int(a["x1"]), int(b["x1"]))
    y1 = max(int(a["y1"]), int(b["y1"]))
    x2 = min(int(a["x2"]), int(b["x2"]))
    y2 = min(int(a["y2"]), int(b["y2"]))
    return max(0, x2 - x1) * max(0, y2 - y1)


def _quad_to_box(points) -> tuple[int, int, int, int]:
    xs = [int(point[0]) for point in points]
    ys = [int(point[1]) for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def _normalize_box(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    text: str,
    confidence: float = 0.0,
) -> dict:
    return {
        "x1": max(0, int(x1)),
        "y1": max(0, int(y1)),
        "x2": max(0, int(x2)),
        "y2": max(0, int(y2)),
        "text": text.strip(),
        "confidence": round(max(0.0, min(1.0, float(confidence))), 4),
    }


def _image_size(image_path: Path) -> tuple[int, int] | None:
    if not importlib.util.find_spec("PIL"):
        return None
    from PIL import Image

    with Image.open(image_path) as image:
        return image.size


def _edge_clip_ratio(box: dict, width: int, height: int, margin: int = 8) -> float:
    touches = 0
    if int(box["x1"]) <= margin:
        touches += 1
    if int(box["y1"]) <= margin:
        touches += 1
    if int(box["x2"]) >= width - margin:
        touches += 1
    if int(box["y2"]) >= height - margin:
        touches += 1
    return touches / 4.0


def _summarize_boxes(boxes: list[dict], size: tuple[int, int] | None) -> dict:
    if not boxes:
        return {
            "text_boxes": 0,
            "overlap_ratio": 0.0,
            "edge_clip_ratio": 0.0,
            "mean_confidence": 0.0,
        }

    box_areas = sum(_box_area(box) for box in boxes) or 1
    overlap_total = 0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            overlap_total += _box_intersection(boxes[i], boxes[j])

    edge_ratio = 0.0
    if size:
        width, height = size
        edge_ratio = max(_edge_clip_ratio(box, width, height) for box in boxes)

    return {
        "text_boxes": len(boxes),
        "overlap_ratio": round(overlap_total / box_areas, 4),
        "edge_clip_ratio": round(edge_ratio, 4),
        "mean_confidence": round(
            statistics.mean(box.get("confidence", 0.0) for box in boxes), 4
        ),
    }


def _result_from_text_and_boxes(
    backend: str,
    text: str,
    boxes: list[dict],
    image_path: Path,
) -> dict:
    summary = _summarize_boxes(boxes, _image_size(image_path) if boxes else None)
    return {
        "enabled": True,
        "backend": backend,
        "text": text.strip(),
        "boxes": boxes,
        "error": "",
        **summary,
    }


def _ocr_with_command(image_path: Path, timeout: int) -> dict | None:
    command = os.getenv("NIMA_OCR_COMMAND")
    if not command:
        return None
    args = shlex.split(command, posix=os.name != "nt") + [str(image_path)]
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "OCR command failed")[-500:])
    output = (result.stdout or "").strip()
    if not output:
        return _result_from_text_and_boxes("command", "", [], image_path)

    try:
        payload = json.loads(output)
    except json.JSONDecodeError:
        return _result_from_text_and_boxes("command", output, [], image_path)

    if isinstance(payload, dict):
        raw_boxes = payload.get("boxes") or []
        boxes = []
        for raw_box in raw_boxes:
            try:
                boxes.append(
                    _normalize_box(
                        raw_box["x1"],
                        raw_box["y1"],
                        raw_box["x2"],
                        raw_box["y2"],
                        text=str(raw_box.get("text") or ""),
                        confidence=float(raw_box.get("confidence") or 0),
                    )
                )
            except Exception:
                continue
        text = str(payload.get("text") or "\n".join(box["text"] for box in boxes))
        return _result_from_text_and_boxes("command", text, boxes, image_path)

    return _result_from_text_and_boxes("command", output, [], image_path)


def _ocr_with_pytesseract(image_path: Path) -> dict | None:
    if not importlib.util.find_spec("pytesseract") or not importlib.util.find_spec(
        "PIL"
    ):
        return None
    import pytesseract
    from PIL import Image

    with Image.open(image_path) as image:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

    boxes = []
    for idx, raw_text in enumerate(data.get("text", [])):
        text = (raw_text or "").strip()
        if not text:
            continue
        try:
            confidence = float(data.get("conf", [0])[idx])
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0:
            continue
        x1 = int(data["left"][idx])
        y1 = int(data["top"][idx])
        width = int(data["width"][idx])
        height = int(data["height"][idx])
        boxes.append(
            _normalize_box(
                x1,
                y1,
                x1 + width,
                y1 + height,
                text=text,
                confidence=confidence / 100.0,
            )
        )

    text = " ".join(box["text"] for box in boxes)
    return _result_from_text_and_boxes("pytesseract", text, boxes, image_path)


def _ocr_with_easyocr(image_path: Path) -> dict | None:
    if not importlib.util.find_spec("easyocr"):
        return None
    global _EASYOCR_READER
    if _EASYOCR_READER is None:
        import easyocr

        _EASYOCR_READER = easyocr.Reader(["en"], gpu=False, verbose=False)

    boxes = []
    for quad, text, confidence in _EASYOCR_READER.readtext(
        str(image_path), detail=1, paragraph=False
    ):
        clean_text = (text or "").strip()
        if not clean_text or float(confidence) < 0.2:
            continue
        x1, y1, x2, y2 = _quad_to_box(quad)
        boxes.append(
            _normalize_box(
                x1,
                y1,
                x2,
                y2,
                text=clean_text,
                confidence=float(confidence),
            )
        )

    text = " ".join(box["text"] for box in boxes)
    return _result_from_text_and_boxes("easyocr", text, boxes, image_path)


def _extract_paddle_lines(payload) -> list[tuple[str, float, tuple[int, int, int, int]]]:
    lines = []
    if not payload:
        return lines
    candidates = payload[0] if isinstance(payload, list) and payload else payload
    for item in candidates or []:
        try:
            quad, text_info = item[0], item[1]
            text, confidence = text_info[0], float(text_info[1])
            lines.append((str(text), confidence, _quad_to_box(quad)))
        except Exception:
            continue
    return lines


def _ocr_with_paddleocr(image_path: Path) -> dict | None:
    if not importlib.util.find_spec("paddleocr"):
        return None
    global _PADDLE_OCR
    if _PADDLE_OCR is None:
        from paddleocr import PaddleOCR

        _PADDLE_OCR = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)

    boxes = []
    for text, confidence, (x1, y1, x2, y2) in _extract_paddle_lines(
        _PADDLE_OCR.ocr(str(image_path), cls=True)
    ):
        clean_text = text.strip()
        if not clean_text or confidence < 0.2:
            continue
        boxes.append(
            _normalize_box(
                x1,
                y1,
                x2,
                y2,
                text=clean_text,
                confidence=confidence,
            )
        )

    text = " ".join(box["text"] for box in boxes)
    return _result_from_text_and_boxes("paddleocr", text, boxes, image_path)


def extract_text_from_image(image_path: str | Path, *, timeout: int = 20) -> dict:
    """Extract text from one image using the first available local OCR backend."""
    path = Path(image_path)
    if not path.exists():
        return _empty_ocr_result(False, None, "missing image")

    try:
        command_result = _ocr_with_command(path, timeout)
        if command_result is not None:
            return command_result
    except Exception as exc:
        return _empty_ocr_result(True, "command", str(exc))

    try:
        pytesseract_result = _ocr_with_pytesseract(path)
        if pytesseract_result is not None:
            return pytesseract_result
    except Exception as exc:
        return _empty_ocr_result(True, "pytesseract", str(exc))

    try:
        easyocr_result = _ocr_with_easyocr(path)
        if easyocr_result is not None:
            return easyocr_result
    except Exception as exc:
        return _empty_ocr_result(True, "easyocr", str(exc))

    try:
        paddleocr_result = _ocr_with_paddleocr(path)
        if paddleocr_result is not None:
            return paddleocr_result
    except Exception as exc:
        return _empty_ocr_result(True, "paddleocr", str(exc))

    backends = available_ocr_backends()
    return _empty_ocr_result(
        False, backends[0] if backends else None, "no local OCR backend configured"
    )


def analyze_frame_ocr_paths(
    frame_paths: Iterable[str | Path], *, timeout: int = 20
) -> dict:
    """Run optional OCR over sampled frame images."""
    backends = available_ocr_backends()
    if not backends:
        return {
            "enabled": False,
            "backend": None,
            "sampled_frames": 0,
            "text_frames": 0,
            "warnings": [],
            "error": "no local OCR backend configured",
        }

    results = []
    warnings = []
    backend = backends[0]
    for frame_path in frame_paths:
        result = extract_text_from_image(frame_path, timeout=timeout)
        backend = result.get("backend") or backend
        if result.get("error"):
            warnings.append(f"{Path(frame_path).name}: {result['error']}")
        results.append(result)

    text_frames = sum(1 for result in results if (result.get("text") or "").strip())
    box_results = [result for result in results if result.get("text_boxes", 0) > 0]
    max_overlap = max((result.get("overlap_ratio", 0.0) for result in box_results), default=0.0)
    max_edge_clip = max(
        (result.get("edge_clip_ratio", 0.0) for result in box_results), default=0.0
    )
    layout_warnings = []
    if max_overlap >= 0.12:
        layout_warnings.append(f"OCR text overlap peak {max_overlap:.2f}")
    if max_edge_clip >= 0.5:
        layout_warnings.append(f"OCR text touches frame edge peak {max_edge_clip:.2f}")

    return {
        "enabled": True,
        "backend": backend,
        "sampled_frames": len(results),
        "text_frames": text_frames,
        "warnings": warnings,
        "layout_warnings": layout_warnings,
        "summary": {
            "mean_text_boxes": round(
                statistics.mean(result.get("text_boxes", 0) for result in results), 2
            )
            if results
            else 0.0,
            "mean_overlap_ratio": round(
                statistics.mean(result.get("overlap_ratio", 0.0) for result in results),
                4,
            )
            if results
            else 0.0,
            "max_overlap_ratio": round(max_overlap, 4),
            "max_edge_clip_ratio": round(max_edge_clip, 4),
            "mean_confidence": round(
                statistics.mean(result.get("mean_confidence", 0.0) for result in box_results),
                4,
            )
            if box_results
            else 0.0,
        },
        "error": "",
    }
