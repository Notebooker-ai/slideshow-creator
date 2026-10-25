"""Preserve process content when a compact diagram cannot fit readable labels."""

import re


def process_bullets(spec: str) -> list[str]:
    items = []
    for line in spec.splitlines():
        label = re.match(r"\s*- label\s+(.+)", line)
        desc = re.match(r"\s+desc\s+(.+)", line)
        if label:
            items.append(label[1].strip().strip('"'))
        elif desc and items:
            items[-1] += ": " + desc[1].strip().strip('"')
    return items


def layout_safe_slide(slide: dict) -> dict:
    spec = slide.get("spec", "")
    template = spec.splitlines()[0] if spec else ""
    bullets = process_bullets(spec)
    if "horizontal" in template and len(bullets) > 3:
        return {k: v for k, v in {**slide, "type": "bullets", "bullets": bullets}.items()
                if k not in ("spec", "svg_path", "png_path")}
    return slide
